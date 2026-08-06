"""The ``skore agent`` command: authenticate, configure and launch a harness."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from skore_cli._hub_auth import ensure_login
from skore_cli._skore import URI_ENV, resolve_hub_uri
from skore_cli._skore import auth as _auth
from skore_cli._style import console
from skore_cli.agent import _client
from skore_cli.agent._harnesses import (
    DEFAULT_MODEL_ID,
    HARNESS_NAMES,
    HARNESSES,
    HarnessContext,
    detect_harnesses,
    launch_harness,
)
from skore_cli.agent._skore_file import SkoreConfig, ensure_gitignore_entry

PROJECT_PERMISSIONS = (
    "create:project",
    "read:project",
    "update:project",
    "delete:project",
)


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _pick_workspace(
    memberships: list[_client.Membership],
) -> _client.Membership:
    """Launch the Textual workspace picker and return the chosen membership."""
    from skore_cli.agent.app import WorkspacePicker

    rows = [(membership.public_id, membership.public_id) for membership in memberships]
    app = WorkspacePicker(rows)
    app.run()
    if app.result is None:
        raise click.Abort()
    return next(m for m in memberships if m.public_id == app.result)


def _pick_harness(workspace: Path) -> str:
    """Launch the Textual harness picker among installed harnesses."""
    from skore_cli.agent.app import HarnessPicker

    detected = detect_harnesses(workspace)
    if not detected:
        raise click.ClickException(
            "no supported harness found on PATH. Install one of: "
            f"{', '.join(HARNESS_NAMES)}."
        )
    rows = [
        (name, HARNESSES[name].label, True) for name in HARNESSES if name in detected
    ]
    app = HarnessPicker(rows, preselect=0)
    app.run()
    if app.result is None:
        raise click.Abort()
    return app.result


def _resolve_api_key_name(harness: str, existing_names: list[str]) -> str:
    if harness not in existing_names:
        return harness
    index = 2
    while f"{harness}-{index}" in existing_names:
        index += 1
    return f"{harness}-{index}"


def _ensure_login(hub_url: str, *, timeout: int) -> str:
    """Return a bearer token, running interactive login when needed."""
    return ensure_login(timeout=timeout)


def _create_workspace_api_key(
    hub_url: str,
    token: str,
    user_id: str,
    membership: _client.Membership,
    harness: str,
) -> str:
    """Mint a workspace-scoped API key for the chosen harness."""
    grantable = set(membership.permissions)
    permissions = [p for p in PROJECT_PERMISSIONS if p in grantable]
    if not permissions:
        raise click.ClickException(
            f"you cannot create project API keys in workspace '{membership.public_id}'."
        )

    existing = _client.list_api_keys(hub_url, token, user_id)
    workspace_names = [
        key.name or ""
        for key in existing
        if key.workspace_id == membership.workspace_id
    ]
    key_name = _resolve_api_key_name(harness, workspace_names)
    _api_key_id, secret = _client.create_api_key(
        hub_url,
        token,
        user_id,
        name=key_name,
        permissions=permissions,
        workspace_id=membership.workspace_id,
        expires_at=None,
    )
    return secret


def _resolve_membership(
    memberships: list[_client.Membership],
    workspace_public_id: str | None,
) -> _client.Membership:
    if workspace_public_id is None:
        if len(memberships) == 1:
            return memberships[0]
        if not _is_interactive():
            raise click.UsageError(
                "pass a saved workspace in .skore or run interactively to pick one."
            )
        return _pick_workspace(memberships)

    membership = next(
        (m for m in memberships if m.public_id == workspace_public_id),
        None,
    )
    if membership is None:
        raise click.ClickException(
            f"workspace '{workspace_public_id}' is not in your memberships."
        )
    return membership


@click.command()
@click.option(
    "--workspace",
    "-w",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Project directory to configure (default: current directory).",
)
@click.option(
    "--hub-url",
    default=None,
    help=(
        "Base URL of the hub (e.g. http://127.0.0.1:8000). Defaults to the "
        f"{URI_ENV} env var or the public hub."
    ),
)
@click.option(
    "--harness",
    "-H",
    "harness_name",
    type=click.Choice(HARNESS_NAMES),
    default=None,
    help="Harness to use non-interactively (omit to pick among installed ones).",
)
@click.option(
    "--model-id",
    default=DEFAULT_MODEL_ID,
    show_default=True,
    help="Model id advertised by the hub.",
)
@click.option(
    "--login-timeout",
    default=600,
    show_default=True,
    help="Seconds to wait for interactive device login.",
)
def agent(
    workspace: Path,
    hub_url: str | None,
    harness_name: str | None,
    model_id: str,
    login_timeout: int,
) -> None:
    """Authenticate, configure and launch a Skore Hub agent harness.

    On the first run, ``skore agent`` logs in to the hub (when needed), lets
    you pick a workspace and harness, creates a workspace API key, writes the
    harness config, and launches the agent. Later runs reuse ``.skore`` in the
    project directory.

    Supported harnesses: Claude, OpenCode, Pi and GitHub Copilot
    (must be on ``PATH``).
    """
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise click.ClickException(f"workspace does not exist: {workspace}")

    config = SkoreConfig.load(workspace)

    if config is not None and config.api_key and config.workspace:
        resolved_hub_url = (
            resolve_hub_uri(hub_url, _auth) if hub_url is not None else config.hub_url
        )
        harness_name = harness_name or config.harness
    else:
        resolved_hub_url = resolve_hub_uri(hub_url, _auth)
        token = _ensure_login(resolved_hub_url, timeout=login_timeout)
        user_id, memberships = _client.me(resolved_hub_url, token)
        if not memberships:
            raise click.ClickException(
                "you are not a member of any hub workspace; create or join one first."
            )

        saved_workspace = config.workspace if config else None
        membership = _resolve_membership(memberships, saved_workspace)

        if config is None or not config.api_key:
            if harness_name is None:
                if not _is_interactive():
                    raise click.UsageError(
                        "pass --harness to create an API key non-interactively."
                    )
                harness_name = _pick_harness(workspace)
            api_key = _create_workspace_api_key(
                resolved_hub_url, token, user_id, membership, harness_name
            )
        else:
            api_key = config.api_key

        config = SkoreConfig(
            hub_url=resolved_hub_url,
            workspace=membership.public_id,
            workspace_id=membership.workspace_id,
            api_key=api_key,
            harness=harness_name or (config.harness if config else None),
        )
        config_path = config.save(workspace)
        ensure_gitignore_entry(workspace)
        console.print(f"[skore.ok]+[/] saved [skore.path]{config_path}[/]")

    if harness_name is None:
        if not _is_interactive():
            raise click.UsageError(
                f"pass --harness <name> (one of: {', '.join(HARNESS_NAMES)})."
            )
        harness_name = _pick_harness(workspace)

    harness = HARNESSES[harness_name]
    if not harness.detect(workspace):
        raise click.ClickException(f"{harness.label} is not installed or not on PATH.")

    if config.harness != harness_name:
        config = SkoreConfig(
            hub_url=config.hub_url,
            workspace=config.workspace,
            workspace_id=config.workspace_id,
            api_key=config.api_key,
            harness=harness_name,
        )
        config.save(workspace)

    console.print(
        f"Configuring [skore.skill]{harness.label}[/] in [skore.path]{workspace}[/]"
    )
    harness.configure(
        HarnessContext(
            workspace=workspace,
            hub_url=config.hub_url,
            api_key=config.api_key,
            model_id=model_id,
        )
    )
    launch_harness(harness_name, workspace, model_id=model_id)
