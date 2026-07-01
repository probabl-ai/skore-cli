"""The ``skore hub`` command group to authenticate with a Skore Hub instance.

Auth mirrors ``skore``'s in-process authentication:

* an **API key** is user-managed through the ``SKORE_HUB_API_KEY`` environment
  variable;
* otherwise ``skore.login()`` runs the interactive device flow and keeps the
  token in memory for the current process.

Heavy ``skore`` imports are deferred into the command callbacks so building the
CLI (and ``--help``) never imports the ``skore`` package.
"""

from __future__ import annotations

import os

import rich_click as click

from skore_cli._hub_auth import API_KEY_ENV, auth_kind, clear_login
from skore_cli._skore import URI_ENV, resolve_hub_uri
from skore_cli._skore import auth as _auth
from skore_cli._style import console

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli hub": [
        {"name": "Authentication", "commands": ["login", "logout", "status"]},
        {"name": "API keys", "commands": ["api-key"]},
        {"name": "Agent", "commands": ["agent-provider"]},
        {"name": "Workspace", "commands": ["workspace"]},
    ],
}


@click.group(invoke_without_command=True)
@click.pass_context
def hub(ctx) -> None:
    """Authenticate this machine with a Skore Hub instance."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@hub.command("login")
@click.option(
    "--hub-url",
    default=None,
    help=(
        "Base URL of the hub (e.g. http://127.0.0.1:8000). Defaults to "
        f"the {URI_ENV} env var or the public hub."
    ),
)
@click.option(
    "--timeout",
    default=600,
    show_default=True,
    help="Seconds to wait for the interactive device login to complete.",
)
def login(hub_url: str | None, timeout: int) -> None:
    """Log in to the hub.

    With an API key (``SKORE_HUB_API_KEY``) there is nothing to do: it is
    user-managed and read from the environment. Without one, run the interactive
    device flow for this process.
    """
    uri = resolve_hub_uri(hub_url, _auth)

    if os.environ.get(API_KEY_ENV):
        console.print(
            f"[skore.ok]Using the API key from[/] [bold]{API_KEY_ENV}[/] "
            f"[skore.ok]for {uri}.[/]\n"
            "  [skore.muted]Nothing is stored; the key is read from the "
            "environment.[/]"
        )
        return

    _auth("login").login(timeout=timeout)


@hub.command("logout")
def logout() -> None:
    """Clear the in-process interactive session.

    The API key (``SKORE_HUB_API_KEY``) is user-managed and not revoked here.
    """
    if clear_login():
        console.print("[skore.ok]-[/] cleared the interactive session.")
        return

    if os.environ.get(API_KEY_ENV):
        console.print(
            f"No interactive session. The API key from [bold]{API_KEY_ENV}[/] is "
            "user-managed; unset it yourself to stop using it."
        )
    else:
        console.print("No interactive session to clear.")


@hub.command("status")
def status() -> None:
    """Show how this process will authenticate to the hub."""
    kind = auth_kind()

    console.print(f"hub URI      : [skore.path]{_auth('uri').URI()}[/]")
    if os.environ.get(API_KEY_ENV):
        console.print(f"API key (env): [skore.ok]set[/] ({API_KEY_ENV})")
    else:
        console.print("API key (env): [skore.muted]not set[/]")

    if kind == "bearer":
        console.print("session      : [skore.ok]interactive token[/] (in memory)")
    elif kind == "api_key":
        console.print("session      : [skore.ok]API key[/] (from environment)")
    else:
        console.print("session      : [skore.muted]none[/]")
        raise click.ClickException(
            "Not authenticated. Set SKORE_HUB_API_KEY or run `skore hub login`."
        )


from skore_cli.hub._agent_providers import (  # noqa: E402
    agent_provider as _agent_provider_group,
)
from skore_cli.hub._api_keys import api_key as _api_key_group  # noqa: E402
from skore_cli.hub._workspaces import workspace as _workspace_group  # noqa: E402

hub.add_command(_api_key_group)
hub.add_command(_agent_provider_group)
hub.add_command(_workspace_group)
