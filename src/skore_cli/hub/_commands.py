"""The ``skore hub`` command group to manage Skore Hub credentials."""

from __future__ import annotations

import rich_click as click
from rich.table import Table

from skore_cli._skore import auth as _auth
from skore_cli._style import console

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli hub": [
        {"name": "Credentials", "commands": ["api-key"]},
    ],
    "cli hub api-key": [
        {"name": "Manage", "commands": ["add", "delete", "list"]},
    ],
}


@click.group(invoke_without_command=True)
@click.pass_context
def hub(ctx) -> None:
    """Manage Skore Hub credentials."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _registry():
    """Import ``skore``'s API-key registry, or fail if ``skore`` is missing."""
    return _auth("registry")


def _host(host: str | None) -> str:
    """Return ``host``, or skore's ``URI()`` when ``host`` is omitted."""
    return host or _auth("uri").URI()


@hub.group("api-key", invoke_without_command=True)
@click.pass_context
def api_key(ctx) -> None:
    """Add, delete and list locally stored Hub API keys."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@api_key.command("add")
@click.argument("key")
@click.option("--host", default=None, help="Hub host URL.")
@click.option("--workspace", required=True, help="Hub workspace to attach the key to.")
def add(key: str, host: str | None, workspace: str) -> None:
    """Store a Hub API key for a workspace."""
    _registry().set(host=_host(host), workspace=workspace, api_key=key)


@api_key.command("delete")
@click.option("--host", default=None, help="Hub host URL.")
@click.option("--workspace", required=True, help="Hub workspace whose key to delete.")
def delete(host: str | None, workspace: str) -> None:
    """Delete a stored Hub API key for a workspace."""
    _registry().delete(host=_host(host), workspace=workspace)


@api_key.command("list")
def list_keys() -> None:
    """List stored Hub API keys."""
    rows = list(_registry().keys())
    if not rows:
        console.print("No API keys stored.")
        return

    table = Table(title="Hub API keys")
    table.add_column("host")
    table.add_column("workspace")
    for stored_host, stored_workspace in rows:
        table.add_row(stored_host, stored_workspace)
    console.print(table)
