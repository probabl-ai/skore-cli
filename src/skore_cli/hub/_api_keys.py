"""The ``skore hub api-key`` click group: ``create``, ``list`` and ``revoke``.

Mint, list and revoke workspace-scoped hub API keys, mirroring the hub UI. Every
command requires a prior ``skore hub login`` (a stored OAuth token); the current
user profile (``/identity/users/me``) provides the workspaces and the
permissions grantable in each. Heavy ``httpx``/``textual`` imports stay deferred
inside the callbacks.
"""

from __future__ import annotations

import calendar
import sys
from datetime import UTC, datetime

import rich_click as click

from skore_cli._skore import URI_ENV, resolve_hub_uri
from skore_cli._skore import auth as _auth
from skore_cli._style import console
from skore_cli.hub import _client
from skore_cli.hub._client import PERMISSIONS

# Local literal (avoids importing the heavy ``skore`` package just for help).
API_KEY_ENV = "SKORE_HUB_API_KEY"

VALIDITY_VALUES = ["1", "3", "6", "never"]

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli hub api-key": [
        {"name": "Manage", "commands": ["create", "list", "revoke"]},
    ],
}


@click.group("api-key", invoke_without_command=True)
@click.pass_context
def api_key(ctx) -> None:
    """Create, list and revoke workspace-scoped hub API keys."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _add_months(start: datetime, months: int) -> datetime:
    """Add ``months`` to ``start``, clamping the day to the target month's end."""
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _expires_at(validity: str) -> str | None:
    """Compute an ISO 8601 UTC expiry from a validity choice (``never`` -> None)."""
    if validity == "never":
        return None
    return _add_months(datetime.now(UTC), int(validity)).isoformat()


def _resolve_session(
    hub_url: str | None,
) -> tuple[str, str, str, list[_client.Membership]]:
    """Resolve hub URL + login token + current user id + workspace memberships."""
    uri = resolve_hub_uri(hub_url, _auth)
    token = _client.require_login_token()
    user_id, memberships = _client.me(uri, token)
    return uri, token, user_id, memberships


_HUB_URL_OPTION = click.option(
    "--hub-url",
    default=None,
    help=(
        "Base URL of the hub (e.g. http://127.0.0.1:8000). Defaults to the "
        f"{URI_ENV} env var or the public hub, like `skore hub login`."
    ),
)


def _print_created(
    secret: str,
    api_key_id: int,
    public_id: str,
    permissions: list[str],
    expires_at: str | None,
) -> None:
    console.print(
        f"\n[skore.ok]+ created API key[/] "
        f"[skore.muted](id {api_key_id}, workspace {public_id})[/]"
    )
    console.print("[yellow]Copy it now -- the hub shows the secret only once:[/]")
    console.print(f"\n  [bold]{secret}[/]\n")
    console.print(f"  permissions : {', '.join(permissions)}")
    console.print(f"  expires     : {expires_at or 'never'}")
    console.print(
        "\n[skore.muted]Use it by exporting it in your shell:[/]\n"
        f'  export {API_KEY_ENV}="{secret}"'
    )


@api_key.command("create")
@_HUB_URL_OPTION
@click.option(
    "--workspace",
    "-w",
    default=None,
    help="Hub workspace (public id) to scope the key to.",
)
@click.option("--name", default=None, help="A label for the key.")
@click.option(
    "--permission",
    "-p",
    "permissions",
    multiple=True,
    type=click.Choice(PERMISSIONS),
    help="Permission to grant (repeatable). Must be grantable in the workspace.",
)
@click.option(
    "--validity",
    type=click.Choice(VALIDITY_VALUES),
    default="3",
    show_default=True,
    help="Months until the key expires, or 'never'.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Skip the interactive form even in a terminal (use the flags as given).",
)
def create(
    hub_url: str | None,
    workspace: str | None,
    name: str | None,
    permissions: tuple[str, ...],
    validity: str,
    yes: bool,
) -> None:
    """Create a workspace-scoped API key.

    In a terminal, omitting ``--workspace`` or ``--permission`` opens an
    interactive form (prefilled with any flags). Non-interactively (or with
    ``--yes``), ``--workspace``, ``--name`` and at least one ``--permission`` are
    required.
    """
    uri, token, user_id, memberships = _resolve_session(hub_url)
    if not memberships:
        raise click.ClickException(
            "you are not a member of any hub workspace; create or join one first."
        )

    by_public = {m.public_id: m for m in memberships}
    grantable = {m.workspace_id: sorted(m.permissions) for m in memberships}

    if _is_interactive() and not yes and (workspace is None or not permissions):
        from skore_cli.hub.app import ApiKeyForm

        preselect = (
            by_public[workspace].workspace_id if workspace in by_public else None
        )
        app = ApiKeyForm(
            [(m.workspace_id, m.public_id) for m in memberships],
            grantable,
            name=name or "",
            permissions=list(permissions),
            validity=validity,
            preselect_workspace_id=preselect,
        )
        app.run()
        if app.result is None:
            console.print("Nothing created.")
            return
        result = app.result
        chosen_name = result.name
        workspace_id = result.workspace_id
        public_id = result.workspace_public_id
        perms = result.permissions
        chosen_validity = result.validity
    else:
        if workspace is None:
            raise click.UsageError(
                "pass --workspace <public-id> (one of: "
                f"{', '.join(by_public) or 'none'})."
            )
        if workspace not in by_public:
            raise click.UsageError(
                f"unknown workspace '{workspace}'; you belong to: "
                f"{', '.join(by_public) or 'none'}."
            )
        if not name:
            raise click.UsageError("pass --name <name> for the key.")
        if not permissions:
            raise click.UsageError(
                f"pass at least one --permission (one of: {', '.join(PERMISSIONS)})."
            )
        membership = by_public[workspace]
        ungranted = [p for p in permissions if p not in membership.permissions]
        if ungranted:
            raise click.UsageError(
                f"you cannot grant {', '.join(ungranted)} in '{workspace}'; "
                f"grantable: {', '.join(sorted(membership.permissions)) or 'none'}."
            )
        chosen_name = name
        workspace_id = membership.workspace_id
        public_id = membership.public_id
        perms = list(permissions)
        chosen_validity = validity

    expires_at = _expires_at(chosen_validity)
    api_key_id, secret = _client.create_api_key(
        uri,
        token,
        user_id,
        name=chosen_name,
        permissions=perms,
        workspace_id=workspace_id,
        expires_at=expires_at,
    )
    _print_created(secret, api_key_id, public_id, perms, expires_at)


@api_key.command("list")
@_HUB_URL_OPTION
@click.option(
    "--workspace",
    "-w",
    default=None,
    help="Only show keys for this workspace (public id).",
)
def list_keys(hub_url: str | None, workspace: str | None) -> None:
    """List your hub API keys (metadata only; secrets are never shown)."""
    uri, token, user_id, memberships = _resolve_session(hub_url)
    public_by_id = {m.workspace_id: m.public_id for m in memberships}

    keys = _client.list_api_keys(uri, token, user_id)
    if workspace is not None:
        wanted = {m.workspace_id for m in memberships if m.public_id == workspace}
        keys = [key for key in keys if key.workspace_id in wanted]

    if not keys:
        console.print("[skore.muted]No API keys.[/]")
        return

    from rich.table import Table

    table = Table(box=None, pad_edge=False)
    for column in ("id", "name", "workspace", "created", "expires"):
        table.add_column(column)
    for key in keys:
        table.add_row(
            str(key.id),
            key.name or "-",
            public_by_id.get(key.workspace_id, str(key.workspace_id)),
            (key.created_at or "-")[:19],
            (key.expires_at or "never")[:19] if key.expires_at else "never",
        )
    console.print(table)


@api_key.command("revoke")
@_HUB_URL_OPTION
@click.option(
    "--id", "api_key_id", type=int, default=None, help="API key id to revoke."
)
@click.option(
    "--yes", is_flag=True, default=False, help="Skip the confirmation prompt."
)
def revoke(hub_url: str | None, api_key_id: int | None, yes: bool) -> None:
    """Revoke (delete) an API key by id, or pick one interactively."""
    uri, token, user_id, memberships = _resolve_session(hub_url)
    public_by_id = {m.workspace_id: m.public_id for m in memberships}

    if api_key_id is None:
        keys = _client.list_api_keys(uri, token, user_id)
        if not keys:
            console.print("[skore.muted]No API keys to revoke.[/]")
            return
        if not _is_interactive():
            raise click.UsageError(
                "pass --id <id> to revoke non-interactively (ids: "
                f"{', '.join(str(key.id) for key in keys)})."
            )
        from skore_cli.hub.app import IdPicker

        labels = [
            (
                key.id,
                f"{key.id}  {key.name or '-'}  "
                f"({public_by_id.get(key.workspace_id, key.workspace_id)})",
            )
            for key in keys
        ]
        app = IdPicker(labels, title="Choose the API key to revoke.")
        app.run()
        if app.result is None:
            console.print("Nothing revoked.")
            return
        api_key_id = app.result

    if not yes:
        click.confirm(f"Revoke API key {api_key_id}?", abort=True)
    _client.delete_api_key(uri, token, user_id, api_key_id)
    console.print(f"[skore.ok]-[/] revoked API key {api_key_id}.")
