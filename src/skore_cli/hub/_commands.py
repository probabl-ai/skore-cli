"""The ``skore hub`` command group to manage Skore Hub credentials."""

from __future__ import annotations

import calendar
import os
import re
import socket
from datetime import datetime, timezone

import rich_click as click
from rich.table import Table

from skore_cli._style import console
from skore_cli.hub import _client
from skore_cli.hub.login import login

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli hub": [
        {"name": "Credentials", "commands": ["api-key"]},
    ],
    "cli hub api-key": [
        {"name": "Manage", "commands": ["generate", "delete", "list"]},
    ],
}

PROJECT_PERMISSIONS = (
    "create:project",
    "read:project",
    "update:project",
    "delete:project",
)


@click.group(invoke_without_command=True)
@click.pass_context
def hub(ctx) -> None:
    """Manage Skore Hub credentials."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _registry():
    """Return ``skore``'s API-key registry."""
    from skore._plugins.hub.authentication import registry

    return registry


def _host(host: str | None) -> str:
    """Return ``host``, or skore's ``URI()`` when ``host`` is omitted."""
    from skore._plugins.hub.authentication import URI

    return host or URI()


def _sanitize_hostname(hostname: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", hostname).strip("-.")
    return cleaned or "host"


def _default_api_key_name(workspace: str) -> str:
    hostname = _sanitize_hostname(socket.gethostname())
    return f"{workspace}-{hostname}"[:150]


def _stored_api_key_id(*, host: str, workspace: str) -> int | None:
    """Return the Hub id stored for this host/workspace, if any."""
    registry = _registry()
    secret = registry.get(host=host, workspace=workspace)
    api_key_id = registry.get_api_key_id(host=host, workspace=workspace)
    if secret is None and api_key_id is None:
        return None
    if secret is None or api_key_id is None:
        raise click.ClickException(
            f"the stored API key for workspace '{workspace}' is incomplete; "
            "delete the local entry and generate a new key."
        )
    return api_key_id


def _revoke_stored_api_key(
    hub_url: str,
    token: str,
    user_id: str,
    workspace: str,
) -> bool:
    """Revoke the locally stored Hub key. Return whether a key was stored."""
    api_key_id = _stored_api_key_id(host=hub_url, workspace=workspace)
    if api_key_id is None:
        return False
    _client.delete_api_key(hub_url, token, user_id, api_key_id)
    _registry().delete(host=hub_url, workspace=workspace)
    return True


def _add_calendar_months(when: datetime, months: int) -> datetime:
    """Add ``months`` to ``when``, clamping the day like date-fns ``addMonths``."""
    month = when.month - 1 + months
    year = when.year + month // 12
    month = month % 12 + 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def _expires_at_from_months(months: int, *, now: datetime | None = None) -> str:
    """Return an ISO-8601 UTC instant ``months`` calendar months after ``now``."""
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    else:
        when = when.astimezone(timezone.utc)
    expiry = _add_calendar_months(when, months)
    return expiry.isoformat(timespec="seconds").replace("+00:00", "Z")


def _expires_at_from_choice(choice: str) -> str | None:
    if choice == "never":
        return None
    return _expires_at_from_months(int(choice))


def _create_workspace_api_key(
    hub_url: str,
    token: str,
    user_id: str,
    membership: _client.Membership,
    name: str,
    expires_at: str | None = None,
) -> tuple[int, str]:
    """Mint a workspace-scoped API key."""
    grantable = set(membership.permissions)
    permissions = [p for p in PROJECT_PERMISSIONS if p in grantable]
    if not permissions:
        raise click.ClickException(
            f"you cannot create project API keys in workspace '{membership.public_id}'."
        )

    return _client.create_api_key(
        hub_url,
        token,
        user_id,
        name=name,
        permissions=permissions,
        workspace_id=membership.workspace_id,
        expires_at=expires_at,
    )


def _membership_for(
    memberships: list[_client.Membership], workspace: str
) -> _client.Membership:
    membership = next((m for m in memberships if m.public_id == workspace), None)
    if membership is None:
        raise click.ClickException(
            f"workspace '{workspace}' is not in your memberships."
        )
    return membership


@hub.group("api-key", invoke_without_command=True)
@click.pass_context
def api_key(ctx) -> None:
    """Generate, delete and list Hub API keys."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@api_key.command("generate")
@click.option("--host", default=None, help="Hub host URL.")
@click.option("--workspace", required=True, help="Hub workspace to mint the key for.")
@click.option(
    "--name",
    default=None,
    help="Name stored on the hub for this key (default: workspace-hostname).",
)
@click.option(
    "--login-timeout",
    default=600,
    show_default=True,
    help="Seconds to wait for interactive device login.",
)
@click.option(
    "--expires",
    type=click.Choice(["1", "3", "6", "never"]),
    default="never",
    show_default=True,
    help="Lifetime in months (1, 3, or 6 months), or never.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Replace a stored key: revoke it on the hub, then mint a new one.",
)
def generate(
    host: str | None,
    workspace: str,
    name: str | None,
    login_timeout: int,
    expires: str,
    force: bool,
) -> None:
    """Mint a workspace-scoped Hub API key and store it locally."""
    if host:
        os.environ["SKORE_HUB_URI"] = host
    hub_url = _host(host)
    key_name = name or _default_api_key_name(workspace)
    if _registry().get(host=hub_url, workspace=workspace) and not force:
        raise click.ClickException(
            f"an API key for workspace '{workspace}' is already stored; "
            "pass --force to replace it."
        )
    token = login(timeout=login_timeout)
    user_id, memberships = _client.me(hub_url, token.access)
    if not memberships:
        raise click.ClickException(
            "you are not a member of any hub workspace; create or join one first."
        )
    membership = _membership_for(memberships, workspace)
    if force:
        _revoke_stored_api_key(hub_url, token.access, user_id, workspace)
    expires_at = _expires_at_from_choice(expires)
    api_key_id, secret = _create_workspace_api_key(
        hub_url,
        token.access,
        user_id,
        membership,
        key_name,
        expires_at=expires_at,
    )
    _registry().set(
        host=hub_url, workspace=workspace, api_key=secret, api_key_id=api_key_id
    )
    if expires_at:
        console.print(
            f"[skore.ok]+[/] generated API key for workspace "
            f"[skore.skill]{workspace}[/] (expires {expires_at})"
        )
        return
    console.print(
        f"[skore.ok]+[/] generated API key for workspace [skore.skill]{workspace}[/]"
    )


@api_key.command("delete")
@click.option("--host", default=None, help="Hub host URL.")
@click.option("--workspace", required=True, help="Hub workspace whose key to delete.")
@click.option(
    "--login-timeout",
    default=600,
    show_default=True,
    help="Seconds to wait for interactive device login.",
)
def delete(host: str | None, workspace: str, login_timeout: int) -> None:
    """Delete a stored Hub API key locally and on the hub."""
    if host:
        os.environ["SKORE_HUB_URI"] = host
    hub_url = _host(host)
    token = login(timeout=login_timeout)
    user_id, memberships = _client.me(hub_url, token.access)
    if not memberships:
        raise click.ClickException(
            "you are not a member of any hub workspace; create or join one first."
        )
    _membership_for(memberships, workspace)
    if not _revoke_stored_api_key(hub_url, token.access, user_id, workspace):
        console.print("No API key stored.")
        return


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
