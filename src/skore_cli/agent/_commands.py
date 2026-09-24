"""The ``skore agent`` command: authenticate, configure and launch a harness."""

from __future__ import annotations

import os
from pathlib import Path

import rich_click as click

from skore_cli._agents import (
    AGENTS,
    DEFAULT_MODEL_ID,
    HARNESS_CHOICES,
    HARNESS_NAMES,
    HarnessContext,
    claude_plugin_ide_ready,
    detect_agent,
    get_harness,
    installed_harnesses,
    is_harness_installed,
    is_non_interactive,
    launch_harness,
    missing_harness_message,
    normalize_harness_name,
    resolve_claude_plugin_harness,
)
from skore_cli._style import console
from skore_cli.agent._skore_file import SkoreConfig, ensure_gitignore_entry
from skore_cli.hub import _client
from skore_cli.hub._commands import _registry, generate
from skore_cli.hub.login import login


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
    """Launch the Textual harness picker.

    Detected harnesses are listed first. Harnesses that are not installed
    on this machine are listed after them.
    """
    from skore_cli.agent.app import HarnessPicker

    installed = {
        harness.harness_name
        for harness in installed_harnesses()
        if harness.harness_name is not None
    }
    harnesses = [agent for agent in AGENTS.values() if agent.harness_name is not None]
    ordered = [agent for agent in harnesses if agent.harness_name in installed]
    ordered += [agent for agent in harnesses if agent.harness_name not in installed]
    rows = [
        (
            agent.harness_name,
            agent.harness_display_name,
            agent.harness_name in installed,
        )
        for agent in ordered
        if agent.harness_name is not None
    ]
    app = HarnessPicker(rows, preselect=0)
    app.run()
    if app.result is None:
        raise click.Abort()
    return app.result


def _api_key_for(ctx, config: SkoreConfig, *, login_timeout: int) -> str:
    """Return the workspace API key, minting one through ``generate`` if absent."""
    registry = _registry()
    api_key = registry.get(host=config.hub_url, workspace=config.workspace)

    if api_key:
        return api_key

    ctx.invoke(
        generate,
        host=config.hub_url,
        workspace=config.workspace,
        name=None,
        login_timeout=login_timeout,
    )

    api_key = registry.get(host=config.hub_url, workspace=config.workspace)

    if not api_key:
        raise click.ClickException(
            f"could not read an API key for workspace '{config.workspace}'."
        )

    return api_key


def _resolve_membership(
    memberships: list[_client.Membership],
) -> _client.Membership:
    if len(memberships) == 1:
        return memberships[0]
    if is_non_interactive():
        raise click.UsageError(
            "pass a saved workspace in .skore or run interactively to pick one."
        )
    return _pick_workspace(memberships)


@click.command()
@click.pass_context
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
        "SKORE_HUB_URI env var or the public hub."
    ),
)
@click.option(
    "--harness",
    "-H",
    "harness_name",
    type=click.Choice(HARNESS_CHOICES),
    default=None,
    help="Harness to use non-interactively (omit to pick one).",
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
    ctx,
    workspace: Path,
    hub_url: str | None,
    harness_name: str | None,
    model_id: str,
    login_timeout: int,
) -> None:
    """Authenticate, configure and launch a Skore Hub agent harness.

    On the first run, ``skore agent`` logs in to the hub (when needed), lets
    you pick a workspace and harness, and saves the workspace and hub URI to
    ``.skore``. The API key itself comes from ``skore hub api-key generate``,
    which is run automatically when no key is stored for that workspace.

    Supported harnesses: Bob Shell, Bob IDE, Claude CLI, Claude UI, Claude
    Plugin (Cursor, VS Code, or VS Code Insiders), Cursor IDE, Cursor CLI,
    OpenCode, Pi, Copilot in VSCode, Copilot CLI and Codex CLI.
    Detection uses ``PATH``, the application bundle on macOS for Bob IDE and
    Claude UI, or the Claude Code IDE extension for Claude Plugin. Claude CLI
    also accepts ``--harness claude-cli``. ``--harness claude-plugin`` asks
    which IDE to open; ``claude-plugin-cursor``, ``claude-plugin-code``, and
    ``claude-plugin-code-insiders`` select that IDE. Bob IDE also accepts
    ``--harness bobide``.
    """
    harness_name = normalize_harness_name(harness_name)
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise click.ClickException(f"workspace does not exist: {workspace}")

    config = SkoreConfig.load(workspace)

    if hub_url:
        os.environ["SKORE_HUB_URI"] = hub_url

        if config is not None:
            from skore._plugins.hub.authentication import URI

            config = SkoreConfig(
                hub_url=URI(),
                workspace=config.workspace,
                workspace_id=config.workspace_id,
                harness=config.harness,
            )

    if config is not None and config.workspace:
        harness_name = harness_name or config.harness
    else:
        from skore._plugins.hub.authentication import URI

        resolved_hub_url = URI()
        token = login(timeout=login_timeout)
        _, memberships = _client.me(resolved_hub_url, token.access)
        if not memberships:
            raise click.ClickException(
                "you are not a member of any hub workspace; create or join one first."
            )

        membership = _resolve_membership(memberships)
        config = SkoreConfig(
            hub_url=resolved_hub_url,
            workspace=membership.public_id,
            workspace_id=membership.workspace_id,
            harness=harness_name,
        )
        config_path = config.save(workspace)
        ensure_gitignore_entry(workspace)
        console.print(f"[skore.ok]+[/] saved [skore.path]{config_path}[/]")

    api_key = _api_key_for(ctx, config, login_timeout=login_timeout)

    if harness_name is None:
        if is_non_interactive():
            detected = detect_agent()
            if detected and detected.harness_name and is_harness_installed(detected):
                harness_name = detected.harness_name
            else:
                raise click.UsageError(
                    f"pass --harness <name> (one of: {', '.join(HARNESS_NAMES)})."
                )
        else:
            harness_name = _pick_harness(workspace)

    if harness_name == "claude-plugin" or claude_plugin_ide_ready(harness_name):
        harness_name = resolve_claude_plugin_harness(harness_name)

    harness = get_harness(harness_name)

    if config.harness != harness_name:
        config = SkoreConfig(
            hub_url=config.hub_url,
            workspace=config.workspace,
            workspace_id=config.workspace_id,
            harness=harness_name,
        )
        config.save(workspace)

    console.print(
        f"Configuring [skore.skill]{harness.harness_display_name}[/] in "
        f"[skore.path]{workspace}[/]"
    )
    assert harness.configure is not None
    harness.configure(
        HarnessContext(
            workspace=workspace,
            hub_url=config.hub_url,
            api_key=api_key,
            model_id=model_id,
        )
    )
    detected = detect_agent()
    if detected and detected.harness_name == harness_name:
        console.print(
            f"[skore.ok]+[/] {harness.harness_display_name} configured with the "
            f"Skore Hub provider. Restart {harness.harness_display_name} or start "
            f"a new session to "
            f"use it."
        )
        return
    if not is_harness_installed(harness):
        raise click.ClickException(missing_harness_message(harness))
    launch_harness(harness, workspace, model_id=model_id)
