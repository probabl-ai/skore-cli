"""The ``skore hub`` command group to manage Skore Hub credentials."""

from __future__ import annotations

import calendar
import os
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


def _resolve_api_key_name(base: str, existing_names: list[str]) -> str:
    if base not in existing_names:
        return base
    index = 2
    while f"{base}-{index}" in existing_names:
        index += 1
    return f"{base}-{index}"


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
) -> str:
    """Mint a workspace-scoped API key."""
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
    key_name = _resolve_api_key_name(name, workspace_names)
    _api_key_id, secret = _client.create_api_key(
        hub_url,
        token,
        user_id,
        name=key_name,
        permissions=permissions,
        workspace_id=membership.workspace_id,
        expires_at=expires_at,
    )
    return secret


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
    help="Name stored on the hub for this key (default: the workspace id).",
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
def generate(
    host: str | None,
    workspace: str,
    name: str | None,
    login_timeout: int,
    expires: str,
) -> None:
    """Mint a workspace-scoped Hub API key and store it locally."""
    if host:
        os.environ["SKORE_HUB_URI"] = host
    hub_url = _host(host)
    token = login(timeout=login_timeout)
    user_id, memberships = _client.me(hub_url, token.access)
    if not memberships:
        raise click.ClickException(
            "you are not a member of any hub workspace; create or join one first."
        )
    membership = _membership_for(memberships, workspace)
    expires_at = _expires_at_from_choice(expires)
    secret = _create_workspace_api_key(
        hub_url,
        token.access,
        user_id,
        membership,
        name or workspace,
        expires_at=expires_at,
    )
    _registry().set(host=hub_url, workspace=workspace, api_key=secret)
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
