"""The ``skore hub`` command group to authenticate with a Skore Hub instance.

Auth mirrors the existing Python authentication:

* an **API key** is user-managed through the ``SKORE_HUB_API_KEY`` environment
  variable -- we never store it; opencode reads it from the environment;
* otherwise an interactive **device-flow** login obtains a (short-lived) token,
  which is the only thing we persist (so a separate opencode process can use it).

The ``api-key`` subgroup (``skore hub api-key``) mints, lists and revokes
workspace-scoped API keys against the hub, mirroring the hub UI. The
``agent-provider`` subgroup manages a workspace's agent LLM provider config, and
the ``workspace`` subgroup manages the lifecycle of the workspaces themselves.
All require a prior ``skore hub login`` (a stored OAuth token).

Heavy ``skore`` imports are deferred into the command callbacks so building the
CLI (and ``--help``) never imports the ``skore`` package.
"""

from __future__ import annotations

import os

import rich_click as click

from skore_cli._skore import URI_ENV, resolve_hub_uri
from skore_cli._skore import auth as _auth
from skore_cli._style import console

# Mirrors ``skore._plugins.hub.authentication`` env var name; kept as a local
# literal so showing help never imports the (heavy) ``skore`` package.
API_KEY_ENV = "SKORE_HUB_API_KEY"

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
    device flow and persist the resulting token locally.
    """
    uri = resolve_hub_uri(hub_url, _auth)

    if os.environ.get(API_KEY_ENV):
        console.print(
            f"[skore.ok]Using the API key from[/] [bold]{API_KEY_ENV}[/] "
            f"[skore.ok]for {uri}.[/]\n"
            "  [skore.muted]Nothing is stored; opencode reads the key from the "
            "environment.[/]"
        )
        return

    # No API key: fall back to the interactive OAuth device flow and persist the
    # token (the only thing we manage -- mirrors the Python `Token` device flow).
    store = _auth("store")

    console.print(f"Logging in to [skore.path]{uri}[/] via interactive device auth.")
    access_token, refresh_token, expires_at = _auth("token").interactive_device_login(
        timeout=timeout
    )

    saved = store.save(
        {
            "uri": uri,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
    )
    console.print(
        f"[skore.ok]+[/] logged in to [skore.path]{uri}[/] (interactive)\n"
        f"  [skore.muted]token -> {saved}[/]\n"
        "[yellow]Note: this token is short-lived; re-run `skore hub login` when it "
        f"expires. For a durable setup, prefer an API key via {API_KEY_ENV}.[/]"
    )


@hub.command("logout")
def logout() -> None:
    """Revoke the interactive token on the hub and remove it locally.

    The API key (``SKORE_HUB_API_KEY``) is user-managed and not revoked here.
    """
    store = _auth("store")

    token = store.load()
    if token and token.get("access_token"):
        post_oauth_logout = _auth("token").post_oauth_logout

        try:
            post_oauth_logout(token["access_token"], token.get("refresh_token"))
            console.print("[skore.ok]+[/] revoked the token on the hub")
        except Exception as error:  # noqa: BLE001 - best-effort revoke; still clear
            console.print(
                f"[yellow]Could not revoke the token on the hub ({error}); "
                "removing it locally anyway.[/]"
            )

    removed = store.clear()
    if removed:
        console.print(f"[skore.ok]-[/] removed stored token ([skore.path]{removed}[/])")
        console.print(
            "  [skore.muted]An existing opencode.json still holds the now-revoked "
            "bearer; re-run `skore hub login` then `skore agent init` to "
            "reconnect.[/]"
        )
    elif os.environ.get(API_KEY_ENV):
        console.print(
            f"No stored token. The API key from [bold]{API_KEY_ENV}[/] is "
            "user-managed; unset it yourself to stop using it."
        )
    else:
        console.print("No stored token to remove.")


@hub.command("status")
def status() -> None:
    """Show how this machine will authenticate to the hub."""
    store = _auth("store")
    token_expired = _auth("token")._token_expired

    has_env_key = bool(os.environ.get(API_KEY_ENV))
    token = store.load()

    console.print(f"hub URI      : [skore.path]{_auth('uri').URI()}[/]")
    if has_env_key:
        console.print(f"API key (env): [skore.ok]set[/] ({API_KEY_ENV})")
    else:
        console.print("API key (env): [skore.muted]not set[/]")
    if token and token.get("access_token"):
        expires_at = token.get("expires_at", "?")
        if token_expired(token.get("expires_at")):
            console.print(f"token        : stored, [yellow]expired[/] ({expires_at})")
        else:
            console.print(f"token        : stored, [skore.ok]valid[/] ({expires_at})")
        console.print(f"token path   : [skore.path]{store.path()}[/]")
    else:
        console.print("token        : [skore.muted]none[/]")

    if not has_env_key and not (token and token.get("access_token")):
        raise click.ClickException(
            "Not authenticated. Set SKORE_HUB_API_KEY or run `skore hub login`."
        )


# The api-key/agent-provider/workspace subgroups are attached here; their heavy
# deps (httpx/textual) stay deferred inside their own command callbacks.
from skore_cli.hub._agent_providers import (  # noqa: E402
    agent_provider as _agent_provider_group,
)
from skore_cli.hub._api_keys import api_key as _api_key_group  # noqa: E402
from skore_cli.hub._workspaces import workspace as _workspace_group  # noqa: E402

hub.add_command(_api_key_group)
hub.add_command(_agent_provider_group)
hub.add_command(_workspace_group)
