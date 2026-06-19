"""The ``skore agent model`` click group: ``install`` and ``status``.

This is the "agent-as-model" integration: the Skore Hub agent is served behind
an OpenAI-compatible endpoint and a local harness is pointed at it. ``install``
configures a harness (and records a ``.skore-agent.json`` marker); ``status``
reports that wiring.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import rich_click as click

from skore_cli._skore import URI_ENV, resolve_hub_uri
from skore_cli._skore import auth as _auth
from skore_cli._style import console
from skore_cli.agent._harnesses import (
    API_KEY_ENV,
    DEFAULT_MODEL_ID,
    HARNESS_NAMES,
    HARNESSES,
    MARKER_FILENAME,
    ConfigureContext,
    Credential,
    base_url,
    detect_harnesses,
    fetch_workspaces,
    resolve_credential,
)

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli agent model": [
        {"name": "OpenAI-compatible endpoint", "commands": ["install", "status"]},
    ],
}


@click.group()
def model() -> None:
    """Use the Skore Hub agent as your harness's model (OpenAI-compatible)."""


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _print_credential(cred: Credential) -> None:
    if cred.kind == "api_key":
        console.print(
            f"Using the API key from [bold]{API_KEY_ENV}[/] "
            "[skore.muted](never written to a file; only referenced).[/]"
        )
    elif cred.kind == "bearer":
        console.print(
            "Using your interactive [bold]skore hub login[/] token "
            "[skore.muted](refreshed automatically).[/]"
        )
    else:
        console.print(
            f"[yellow]No credential found. Set {API_KEY_ENV} (recommended) or run "
            "`skore hub login` for interactive authentication, then re-run.[/]"
        )


def _install_skills(workspace: Path, install: bool) -> None:
    if not install:
        return
    console.print(
        "[yellow]Note: installing skills locally is OFF by default for IP "
        "isolation. The hub agent loads skills server-side; local skills are not "
        "needed.[/]"
    )
    console.print(
        "Installing probabl-skills into the workspace (--skills override) ..."
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "skore_cli", "skills", "install", "--all"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        console.print(f"[yellow]  could not run skills install: {error}[/]")
        return
    if result.returncode != 0:
        console.print(
            "[yellow]  skills install failed (continuing); run "
            "`skore skills install --all` manually.\n  "
            f"{(result.stderr or '').strip()}[/]"
        )
    else:
        console.print("[skore.ok]  skills installed.[/]")


def _pick_harness(workspace: Path) -> str | None:
    """Launch the Textual picker (textual imported lazily) and return a name."""
    from skore_cli.agent.app import HarnessPicker

    detected = set(detect_harnesses(workspace))
    rows = [
        (name, harness.label, name in detected) for name, harness in HARNESSES.items()
    ]
    preselect = next((i for i, row in enumerate(rows) if row[2]), 0)

    app = HarnessPicker(rows, preselect=preselect)
    app.run()
    return app.result


def _pick_workspace(workspaces: list[tuple[str, str]]) -> str | None:
    """Launch the Textual workspace picker and return the chosen public id."""
    from skore_cli.agent.app import WorkspacePicker

    app = WorkspacePicker(workspaces)
    app.run()
    return app.result


def _resolve_hub_workspace(
    cred: Credential, hub_url: str, hub_workspace: str | None
) -> str | None:
    """Resolve the hub workspace the agent should attach to.

    API keys are already workspace-bound server-side, so nothing is attached for
    them. For the interactive (bearer) path the workspace must be explicit: from
    ``--hub-workspace`` or an interactive picker; otherwise this errors, because
    the hub now rejects agent calls that resolve to no workspace.
    """
    if cred.kind == "api_key":
        if hub_workspace:
            console.print(
                "[yellow]Ignoring --hub-workspace: the workspace is fixed by your "
                f"API key ({API_KEY_ENV}).[/]"
            )
        else:
            console.print(
                f"[skore.muted]Workspace is fixed by your API key ({API_KEY_ENV}).[/]"
            )
        return None

    if cred.kind != "bearer":
        # No credential: nothing can be attached; install already warns about this.
        return None

    if hub_workspace:
        return hub_workspace

    try:
        workspaces = fetch_workspaces(hub_url, cred)
    except Exception as error:  # noqa: BLE001 - surfaced as a friendly CLI error
        raise click.ClickException(
            f"could not list your hub workspaces ({error}); pass "
            "--hub-workspace <slug> to attach one explicitly."
        ) from error

    if not workspaces:
        raise click.ClickException(
            "you are not a member of any hub workspace; create or join one, then retry."
        )

    if not _is_interactive():
        raise click.UsageError(
            "pass --hub-workspace <slug> to attach a workspace non-interactively "
            f"(one of: {', '.join(public_id for public_id, _ in workspaces)})."
        )

    chosen = _pick_workspace(workspaces)
    if chosen is None:
        raise click.ClickException("no workspace selected.")
    return chosen


@model.command("install")
@click.option(
    "--workspace",
    "-w",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Workspace directory to configure (default: current directory).",
)
@click.option(
    "--harness",
    "-H",
    "harness_name",
    type=click.Choice(HARNESS_NAMES),
    default=None,
    help="Harness to configure non-interactively (omit to pick interactively).",
)
@click.option(
    "--hub-url",
    default=None,
    help=(
        "Base URL of the hub (e.g. http://127.0.0.1:8000). Defaults to the "
        f"{URI_ENV} env var or the public hub, like `skore hub login`."
    ),
)
@click.option(
    "--hub-workspace",
    default=None,
    help=(
        "Hub workspace (public id) to attach the agent to. Required for "
        "interactive-login (bearer) auth in non-interactive mode; ignored when a "
        "workspace-scoped API key is used."
    ),
)
@click.option(
    "--model-id",
    default=DEFAULT_MODEL_ID,
    help="Model id advertised by the hub (default: skore-agent).",
)
@click.option(
    "--skills/--no-skills",
    "install_skills",
    default=False,
    help="Install probabl-skills locally (default: off; the hub serves skills).",
)
@click.option(
    "--session-plugin/--no-session-plugin",
    "write_session_plugin",
    default=True,
    help="opencode only: write the session-binding plugin (default: on).",
)
@click.option(
    "--config-file/--no-config-file",
    "write_file",
    default=True,
    help="generic only: also write skore-agent.json (default: on).",
)
def install(
    workspace: Path,
    harness_name: str | None,
    hub_url: str | None,
    hub_workspace: str | None,
    model_id: str,
    install_skills: bool,
    write_session_plugin: bool,
    write_file: bool,
) -> None:
    """Configure an agent harness to talk to the Skore Hub agent.

    Pass ``--harness <name>`` to configure a specific harness non-interactively;
    omit it in a terminal to pick one interactively (like ``skore skills``). The
    ``generic`` harness just prints the connection values for any other
    OpenAI-compatible client.
    """
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise click.ClickException(f"workspace does not exist: {workspace}")

    if harness_name is None:
        if _is_interactive():
            harness_name = _pick_harness(workspace)
            if harness_name is None:
                console.print("Nothing selected.")
                return
        else:
            raise click.UsageError(
                "Specify --harness <name> to configure non-interactively "
                f"(one of: {', '.join(HARNESS_NAMES)})."
            )

    harness = HARNESSES[harness_name]
    console.print(
        f"Configuring [skore.skill]{harness.name}[/] in: [skore.path]{workspace}[/]"
    )

    cred = resolve_credential()
    _print_credential(cred)

    # Resolve the hub address the same way `skore hub login` does (explicit
    # --hub-url, else SKORE_HUB_URI, else the public hub).
    hub_url = resolve_hub_uri(hub_url, _auth)

    attached_workspace = _resolve_hub_workspace(cred, hub_url, hub_workspace)
    if attached_workspace:
        console.print(
            f"Attaching to hub workspace [skore.skill]{attached_workspace}[/]."
        )

    _install_skills(workspace, install_skills)

    ctx = ConfigureContext(
        workspace=workspace,
        hub_url=hub_url,
        model_id=model_id,
        cred=cred,
        hub_workspace=attached_workspace,
        write_session_plugin=write_session_plugin,
        write_file=write_file,
    )
    extra = harness.configure(ctx)

    marker = {
        "harness": harness.name,
        "hub_url": hub_url,
        "base_url": base_url(hub_url),
        "hub_workspace": attached_workspace,
        "model_id": model_id,
        "auth": cred.kind,
        "session_binding": harness.session_binding,
        **extra,
    }
    marker_path = workspace / MARKER_FILENAME
    marker_path.write_text(json.dumps(marker, indent=2) + "\n")
    console.print(f"\n[skore.muted]Recorded the setup in {marker_path}.[/]")


@model.command("status")
@click.option(
    "--workspace",
    "-w",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Workspace directory to inspect (default: current directory).",
)
def status(workspace: Path) -> None:
    """Show the agent wiring for this workspace."""
    workspace = workspace.resolve()
    marker_path = workspace / MARKER_FILENAME
    if not marker_path.exists():
        raise click.ClickException(
            f"no {MARKER_FILENAME} in {workspace}; "
            "run `skore agent model install` first."
        )

    marker = json.loads(marker_path.read_text() or "{}")
    harness_name = marker.get("harness", "?")
    base = marker.get("base_url", "?")
    model_id = marker.get("model_id", "?")
    auth = marker.get("auth", "none")
    binding = marker.get("session_binding", "fallback")
    hub_workspace = marker.get("hub_workspace")

    skills_dir = workspace / ".agents" / "skills"
    n_skills = len(list(skills_dir.iterdir())) if skills_dir.is_dir() else 0
    skills_note = (
        f"{n_skills} local (override)" if n_skills else "served by hub (none local)"
    )

    auth_note = {
        "api_key": f"[skore.ok]API key[/] (from {API_KEY_ENV})",
        "bearer": "[skore.ok]interactive token[/]",
        "none": "[skore.muted]none[/]",
    }.get(auth, auth)

    session_note = (
        "[skore.ok]bound[/] via the X-Skore-Session-Id header"
        if binding == "plugin"
        else "[skore.muted]via the OpenAI 'user' field, else content-hash fallback[/]"
    )

    workspace_note = (
        f"[skore.skill]{hub_workspace}[/]"
        if hub_workspace
        else "[skore.muted]bound by API key (no header)[/]"
        if auth == "api_key"
        else "[skore.muted]none[/]"
    )

    console.print(f"workspace : [skore.path]{workspace}[/]")
    console.print(f"harness   : [skore.skill]{harness_name}[/]")
    console.print(f"hub URL   : [skore.path]{base}[/]")
    console.print(f"hub ws    : {workspace_note}")
    console.print(f"model     : {model_id}")
    console.print(f"auth      : {auth_note}")
    console.print(f"skills    : {skills_note}")
    console.print(f"session   : {session_note}")
