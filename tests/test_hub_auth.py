"""Tests for ``_hub_auth`` login gating."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import rich_click as click

from skore_cli import _hub_auth


class _Token:
    def __init__(self, access: str = "acc"):
        self.access = access


@pytest.fixture
def skore_auth(monkeypatch):
    """Stand in for ``skore``'s ``login`` and ``token`` modules."""
    token_mod = SimpleNamespace(token=None)
    login_mod = SimpleNamespace(login_calls=0)

    def login(*, timeout=600):
        login_mod.login_calls += 1
        if login_mod.mints_token:
            token_mod.token = _Token()

    login_mod.mints_token = True
    login_mod.login = login
    monkeypatch.setattr(_hub_auth, "_login_module", lambda: login_mod)
    monkeypatch.setattr(_hub_auth, "_token_module", lambda: token_mod)
    return SimpleNamespace(login=login_mod, token=token_mod)


def test_auth_kind_none(monkeypatch, skore_auth):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    assert _hub_auth.auth_kind() == "none"


def test_auth_kind_api_key_from_env(monkeypatch, skore_auth):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    assert _hub_auth.auth_kind() == "api_key"


def test_auth_kind_bearer(monkeypatch, skore_auth):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    skore_auth.token.token = _Token("tok")
    assert _hub_auth.auth_kind() == "bearer"
    assert _hub_auth.bearer_token() == "tok"


def test_ensure_login_runs_login_when_needed(monkeypatch, skore_auth):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    assert _hub_auth.ensure_login(timeout=30) == "acc"
    assert skore_auth.login.login_calls == 1


def test_ensure_login_rejects_env_api_key(monkeypatch, skore_auth):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    with pytest.raises(click.ClickException):
        _hub_auth.ensure_login()


def test_bearer_token_none_without_token(skore_auth):
    assert _hub_auth.bearer_token() is None


def test_ensure_login_skips_login_when_already_authenticated(monkeypatch, skore_auth):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    skore_auth.token.token = _Token("tok")
    assert _hub_auth.ensure_login() == "tok"
    assert skore_auth.login.login_calls == 0


def test_ensure_login_raises_when_token_missing(monkeypatch, skore_auth):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    skore_auth.login.mints_token = False
    with pytest.raises(click.ClickException, match="not logged in"):
        _hub_auth.ensure_login()


def test_clear_login_returns_false_without_session(skore_auth):
    assert _hub_auth.clear_login() is False


def test_clear_login_drops_session(skore_auth):
    skore_auth.token.token = _Token("tok")
    assert _hub_auth.clear_login() is True
    assert skore_auth.token.token is None
