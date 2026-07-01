"""Bridge ``skore-cli`` to ``skore``'s in-process hub authentication."""

from __future__ import annotations

import os
from typing import Literal

import rich_click as click

from skore_cli._skore import auth as _auth

API_KEY_ENV = "SKORE_HUB_API_KEY"
AuthKind = Literal["api_key", "bearer", "none"]


def _login_module():
    return _auth("login")


def auth_kind() -> AuthKind:
    """Return how the current process authenticates to the hub."""
    credentials = _login_module().credentials
    if credentials is None:
        if os.environ.get(API_KEY_ENV):
            return "api_key"
        return "none"
    headers = credentials()
    if "Authorization" in headers:
        return "bearer"
    if "X-API-Key" in headers:
        return "api_key"
    return "none"


def bearer_token() -> str | None:
    """Return the current OAuth access token, if logged in interactively."""
    credentials = _login_module().credentials
    if credentials is None:
        return None
    authorization = credentials().get("Authorization", "")
    if authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")
    return None


def ensure_login(*, timeout: int = 600) -> str:
    """Ensure an interactive session exists and return its bearer access token."""
    if auth_kind() == "api_key":
        raise click.ClickException(
            "set up a workspace API key with an interactive login first; "
            f"`{API_KEY_ENV}` alone cannot mint project keys."
        )

    login_mod = _login_module()
    if login_mod.credentials is None:
        login_mod.login(timeout=timeout)

    token = bearer_token()
    if not token:
        raise click.ClickException(
            "not logged in; run `skore hub login` or `skore agent` again."
        )
    return token


def clear_login() -> bool:
    """Drop in-process hub credentials. Returns whether a session was cleared."""
    login_mod = _login_module()
    if login_mod.credentials is None:
        return False
    login_mod.credentials = None
    return True
