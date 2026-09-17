"""Bridge ``skore-cli`` to ``skore``'s in-process hub authentication."""

from __future__ import annotations

import os
from typing import Literal

import rich_click as click

API_KEY_ENV = "SKORE_HUB_API_KEY"
AuthKind = Literal["api_key", "bearer", "none"]


def _login_module():
    from skore._plugins.hub.authentication import login

    return login


def _token_module():
    from skore._plugins.hub.authentication import token

    return token


def auth_kind() -> AuthKind:
    """Return how the current process authenticates to the hub."""
    if os.environ.get(API_KEY_ENV):
        return "api_key"
    if _token_module().token is not None:
        return "bearer"
    return "none"


def bearer_token() -> str | None:
    """Return the current OAuth access token, if logged in interactively."""
    token = _token_module().token
    if token is None:
        return None
    return token.access


def ensure_login(*, timeout: int = 600) -> str:
    """Ensure an interactive session exists and return its bearer access token."""
    if auth_kind() == "api_key":
        raise click.ClickException(
            "set up a workspace API key with an interactive login first; "
            f"`{API_KEY_ENV}` alone cannot mint project keys."
        )

    token_mod = _token_module()
    if token_mod.token is None:
        _login_module().login(timeout=timeout)

    token = bearer_token()
    if not token:
        raise click.ClickException("not logged in; run `skore agent` again.")
    return token


def clear_login() -> bool:
    """Drop the in-process OAuth token. Returns whether a session was cleared."""
    token_mod = _token_module()
    if token_mod.token is None:
        return False
    token_mod.token = None
    return True
