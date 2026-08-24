"""Bridge ``skore-cli`` to ``skore``'s in-process hub authentication."""

from __future__ import annotations

import os

import rich_click as click

from skore_cli._skore import auth as _auth

API_KEY_ENV = "SKORE_HUB_API_KEY"


def _login_module():
    return _auth("login")


def api_key_from_env() -> str | None:
    """Return the API key supplied for non-interactive authentication."""
    return os.environ.get(API_KEY_ENV) or None


def ensure_bearer_token(*, timeout: int = 600) -> str:
    """Ensure an interactive session exists and return its bearer access token."""
    if api_key_from_env():
        raise click.ClickException(
            f"{API_KEY_ENV} is set; unset it to use interactive login."
        )

    login_mod = _login_module()
    if login_mod.credentials is None:
        login_mod.login(timeout=timeout)

    if login_mod.credentials is None:
        raise click.ClickException("interactive login did not return credentials.")

    authorization = login_mod.credentials().get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise click.ClickException("interactive login did not return a bearer token.")
    return authorization.removeprefix("Bearer ")
