"""The ``skore hub workspace`` group: list/show/create/rename/delete.

Manage the lifecycle of the hub workspaces you belong to, mirroring the hub UI.
Every command requires a prior ``skore hub login`` (a stored OAuth token).
Commands that target one workspace take ``-w/--workspace`` (a public id) or, in
a terminal, fall back to an interactive picker. Heavy ``httpx``/``textual``
imports stay deferred inside the callbacks.
"""

from __future__ import annotations

import rich_click as click

from skore_cli._style import console
from skore_cli.hub import _client
from skore_cli.hub._agent_providers import _resolve_target_workspace
from skore_cli.hub._api_keys import (
    _HUB_URL_OPTION,
    _is_interactive,
    _resolve_session,
)

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli hub workspace": [
        {"name": "Manage", "commands": ["list", "show", "create", "rename", "delete"]},
    ],
}


@click.group("workspace", invoke_without_command=True)
@click.pass_context
def workspace(ctx) -> None:
    """List, show, create, rename and delete hub workspaces."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _role_for(ws: _client.WorkspaceInfo, user_id: str) -> str:
    for member in ws.members or []:
        if member.user_id == user_id:
            return member.role or "-"
    return "-"


@workspace.command("list")
@_HUB_URL_OPTION
def list_workspaces(hub_url: str | None) -> None:
    """List every workspace you belong to."""
    uri, token, user_id, _memberships = _resolve_session(hub_url)
    workspaces = _client.list_workspaces(uri, token)

    if not workspaces:
        console.print("[skore.muted]No workspaces.[/]")
        return

    from rich.table import Table

    table = Table(box=None, pad_edge=False)
    for column in ("id", "public_id", "public", "created", "members", "role"):
        table.add_column(column)
    for ws in workspaces:
        table.add_row(
            str(ws.id),
            ws.public_id,
            "yes" if ws.is_public else "-",
            (ws.created_at or "-")[:19],
            str(len(ws.members or [])),
            _role_for(ws, user_id),
        )
    console.print(table)


@workspace.command("show")
@_HUB_URL_OPTION
@click.option(
    "--workspace", "-w", default=None, help="Hub workspace (public id) to show."
)
def show(hub_url: str | None, workspace: str | None) -> None:
    """Show a workspace and its members."""
    uri, token, _user_id, memberships = _resolve_session(hub_url)
    membership = _resolve_target_workspace(
        memberships, workspace, interactive=_is_interactive()
    )
    ws = _client.get_workspace(uri, token, membership.workspace_id)

    console.print(f"[skore.ok]workspace[/] [bold]{ws.public_id}[/]")
    console.print(f"  id      : {ws.id}")
    console.print(f"  public  : {'yes' if ws.is_public else 'no'}")
    console.print(f"  created : {(ws.created_at or '-')[:19]}")

    if not ws.members:
        console.print("[skore.muted]  no members.[/]")
        return

    from rich.table import Table

    table = Table(box=None, pad_edge=False)
    for column in ("user_id", "role", "invited_by"):
        table.add_column(column)
    for member in ws.members:
        table.add_row(member.user_id, member.role or "-", member.invited_by or "-")
    console.print(table)


@workspace.command("create")
@_HUB_URL_OPTION
@click.option("--public-id", default=None, help="Public id (slug) for the workspace.")
def create(hub_url: str | None, public_id: str | None) -> None:
    """Create a new workspace (you become its owner)."""
    uri, token, _user_id, _memberships = _resolve_session(hub_url)

    if public_id is None:
        if not _is_interactive():
            raise click.UsageError("pass --public-id <slug> for the workspace.")
        public_id = click.prompt("Workspace public id").strip()
    if not public_id:
        raise click.UsageError("the workspace public id must not be empty.")

    available, suggested = _client.check_public_id(uri, token, public_id)
    if not available:
        hint = f" try '{suggested}'." if suggested else ""
        raise click.ClickException(
            f"workspace public id '{public_id}' is not available.{hint}"
        )

    workspace_id = _client.create_workspace(uri, token, public_id=public_id)
    # The hub may slugify/suffix the id; re-fetch to print the stored value.
    created = _client.get_workspace(uri, token, workspace_id)
    console.print(
        f"[skore.ok]+ created workspace[/] "
        f"[skore.muted](id {created.id})[/] [bold]{created.public_id}[/]"
    )


@workspace.command("rename")
@_HUB_URL_OPTION
@click.option(
    "--workspace", "-w", default=None, help="Hub workspace (public id) to rename."
)
@click.option("--new-public-id", default=None, help="The new public id (slug).")
def rename(
    hub_url: str | None, workspace: str | None, new_public_id: str | None
) -> None:
    """Rename a workspace (change its public id); needs owner/admin."""
    uri, token, _user_id, memberships = _resolve_session(hub_url)
    membership = _resolve_target_workspace(
        memberships, workspace, interactive=_is_interactive()
    )

    if new_public_id is None:
        if not _is_interactive():
            raise click.UsageError("pass --new-public-id <slug>.")
        new_public_id = click.prompt("New public id").strip()
    if not new_public_id:
        raise click.UsageError("the new public id must not be empty.")

    _client.update_workspace(
        uri, token, membership.workspace_id, public_id=new_public_id
    )
    # The hub may slugify the id; re-fetch to print the stored value.
    renamed = _client.get_workspace(uri, token, membership.workspace_id)
    console.print(
        f"[skore.ok]+[/] renamed workspace [skore.muted](id {renamed.id})[/] "
        f"to [bold]{renamed.public_id}[/]"
    )


@workspace.command("delete")
@_HUB_URL_OPTION
@click.option(
    "--workspace", "-w", default=None, help="Hub workspace (public id) to delete."
)
@click.option(
    "--yes", is_flag=True, default=False, help="Skip the confirmation prompt."
)
def delete(hub_url: str | None, workspace: str | None, yes: bool) -> None:
    """Delete a workspace; owner only and irreversible."""
    uri, token, _user_id, memberships = _resolve_session(hub_url)
    membership = _resolve_target_workspace(
        memberships, workspace, interactive=_is_interactive()
    )

    if not yes:
        click.confirm(
            f"Delete workspace '{membership.public_id}'? This is irreversible.",
            abort=True,
        )
    _client.delete_workspace(uri, token, membership.workspace_id)
    console.print(f"[skore.ok]-[/] deleted workspace {membership.public_id}.")
