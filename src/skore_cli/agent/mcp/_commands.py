"""The ``skore agent mcp`` click group: ``serve``, ``install`` and ``status``.

``serve`` runs the local stdio delegation relay (the outer LLM's bridge to the
Skore Hub agent); ``install`` registers that ``serve`` command with a specific
MCP host; ``status`` reports where the relay is registered. ``serve``/``install``
resolve the hub URL the same way as ``skore hub login`` and gate on a Skore Hub
credential; ``status`` is read-only and never refreshes credentials.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import rich_click as click

from skore_cli._skore import URI_ENV, resolve_hub_uri
from skore_cli._skore import auth as _auth
from skore_cli._style import console
from skore_cli.agent._harnesses import (
    API_KEY_ENV,
    DEFAULT_MODEL_ID,
    Credential,
    resolve_credential,
)
from skore_cli.agent.mcp._hosts import HOST_NAMES

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli agent mcp": [
        {"name": "Delegation relay", "commands": ["serve", "install", "status"]},
    ],
}


@click.group()
def mcp() -> None:
    """Delegate ML tasks to the Skore Hub agent from any MCP host."""


def _resolve_serve_workspace(cred: Credential, hub_workspace: str | None) -> str | None:
    """Resolve the hub workspace to send with relay requests.

    API keys are already workspace-bound server-side (nothing is sent). For the
    interactive (bearer) path the workspace must be explicit, since the hub
    rejects agent calls that resolve to no workspace.
    """
    if cred.kind != "bearer":
        return None
    if hub_workspace:
        return hub_workspace
    raise click.UsageError(
        "pass --hub-workspace <slug> to scope the agent for interactive-login "
        "(bearer) auth, or use a workspace-scoped API key (SKORE_HUB_API_KEY)."
    )


def _print_credential(cred: Credential) -> None:
    if cred.kind == "api_key":
        console.print(f"Using the API key from [bold]{API_KEY_ENV}[/].")
    elif cred.kind == "bearer":
        console.print("Using your interactive [bold]skore hub login[/] token.")
    else:
        console.print(
            f"[yellow]No credential found. Set {API_KEY_ENV} or run "
            "`skore hub login` before launching the host.[/]"
        )


@mcp.command("serve")
@click.option(
    "--workspace",
    "-w",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Workspace directory the agent acts in (default: current directory).",
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
        "Hub workspace (public id) to scope the agent to. Required for "
        "interactive-login (bearer) auth; ignored with a workspace-scoped API key."
    ),
)
@click.option(
    "--model-id",
    default=DEFAULT_MODEL_ID,
    help="Model id advertised by the hub (default: skore-agent).",
)
def serve(
    workspace: Path,
    hub_url: str | None,
    hub_workspace: str | None,
    model_id: str,
) -> None:
    """Run the local stdio MCP relay bridging the outer LLM to the Skore agent.

    This is the command MCP hosts launch (see ``skore agent mcp install``). It
    speaks the MCP stdio protocol on stdout, so all diagnostics go to stderr.
    """
    # stdout is the MCP transport: route logging to stderr only.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    mcp_logger = logging.getLogger("skore_cli.agent.mcp")
    mcp_logger.addHandler(handler)
    mcp_logger.setLevel(logging.INFO)

    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise click.ClickException(f"workspace does not exist: {workspace}")

    cred = resolve_credential()
    if cred.kind == "none":
        raise click.ClickException(
            f"no hub credential found. Set {API_KEY_ENV} (recommended) or run "
            "`skore hub login`, then start `skore agent mcp serve` again."
        )
    attached = _resolve_serve_workspace(cred, hub_workspace)
    hub_url = resolve_hub_uri(hub_url, _auth)

    from skore_cli.agent.mcp._a2a_client import RelayConfig
    from skore_cli.agent.mcp._server import build_mcp_server

    config = RelayConfig(
        default_workspace=workspace,
        hub_url=hub_url,
        hub_workspace=attached,
        cred=cred,
    )
    server = build_mcp_server(config)
    server.run()


@mcp.command("install")
@click.option(
    "--host",
    "-H",
    "host_name",
    type=click.Choice(HOST_NAMES),
    default="generic",
    help="MCP host to configure (default: generic, which prints the command).",
)
@click.option(
    "--workspace",
    "-w",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Workspace directory to configure (default: current directory).",
)
@click.option(
    "--hub-url",
    default=None,
    help=(
        "Base URL of the hub (e.g. http://127.0.0.1:8000). Defaults to the "
        f"{URI_ENV} env var or the public hub. Baked into the registered "
        "`serve` command."
    ),
)
@click.option(
    "--hub-workspace",
    default=None,
    help=(
        "Hub workspace (public id) baked into the registered `serve` command. "
        "Required for interactive-login (bearer) auth; ignored with an API key."
    ),
)
def install(
    host_name: str,
    workspace: Path,
    hub_url: str | None,
    hub_workspace: str | None,
) -> None:
    """Register ``skore agent mcp serve`` with an MCP host."""
    from skore_cli.agent.mcp._hosts import HOSTS, InstallContext

    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise click.ClickException(f"workspace does not exist: {workspace}")

    cred = resolve_credential()
    _print_credential(cred)

    hub_url = resolve_hub_uri(hub_url, _auth)
    attached = _resolve_serve_workspace(cred, hub_workspace)

    host = HOSTS[host_name]
    console.print(f"Registering the Skore relay for [skore.skill]{host.name}[/].")
    host.configure(
        InstallContext(workspace=workspace, hub_url=hub_url, hub_workspace=attached)
    )


@mcp.command("status")
@click.option(
    "--workspace",
    "-w",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Workspace directory to inspect (default: current directory).",
)
def status(workspace: Path) -> None:
    """Show where the delegation relay is registered for this workspace.

    Read-only and non-interactive: it never refreshes credentials. It reports the
    resolved hub URL (from the env/default), whether an API key is set, and which
    MCP hosts have ``skore-ml`` registered (with the baked ``serve`` args).
    """
    from skore_cli.agent.mcp._hosts import installed

    workspace = workspace.resolve()

    hub_url = resolve_hub_uri(None, _auth)
    api_key_note = (
        f"[skore.ok]set[/] (from {API_KEY_ENV})"
        if os.environ.get(API_KEY_ENV)
        else f"[skore.muted]not set[/] (run `skore hub login` or set {API_KEY_ENV})"
    )

    console.print(f"workspace : [skore.path]{workspace}[/]")
    console.print(f"hub URL   : [skore.path]{hub_url}[/]")
    console.print(f"API key   : {api_key_note}")
    console.print("hosts     :")

    for host in installed(workspace):
        if host.present:
            baked = " ".join(host.serve_args or []) or "(defaults)"
            console.print(
                f"  [skore.ok]+[/] [skore.skill]{host.name}[/] "
                f"[skore.muted]{host.config_path}[/]\n"
                f"      args: [skore.path]{baked}[/]"
            )
        else:
            console.print(
                f"  [skore.muted]- {host.name} (not registered; {host.config_path})[/]"
            )
