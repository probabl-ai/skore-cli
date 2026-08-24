"""Tests for ``_hub_auth`` login gating."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import rich_click as click

from skore_cli import _hub_auth


class _TokenCreds:
    def __init__(self, token: str = "acc"):
        self._token = token

    def __call__(self):
        return {"Authorization": f"Bearer {self._token}"}


def _make_login(*, credentials=None):
    login_mod = SimpleNamespace(credentials=credentials, login_calls=0)

    def login(*, timeout=600):
        login_mod.login_calls += 1
        login_mod.credentials = _TokenCreds()

    login_mod.login = login
    return lambda name: login_mod


def test_api_key_reads_environment(monkeypatch):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    assert _hub_auth.api_key() == "uid:secret"


def test_api_key_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    assert _hub_auth.api_key() is None


def test_auth_kind_none(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    monkeypatch.setattr(_hub_auth, "_auth", _make_login())
    assert _hub_auth.auth_kind() == "none"


def test_auth_kind_api_key_from_env(monkeypatch):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    monkeypatch.setattr(_hub_auth, "_auth", _make_login())
    assert _hub_auth.auth_kind() == "api_key"


def test_auth_kind_bearer(monkeypatch):
    monkeypatch.setattr(_hub_auth, "_auth", _make_login(credentials=_TokenCreds("tok")))
    assert _hub_auth.auth_kind() == "bearer"
    assert _hub_auth.bearer_token() == "tok"


def test_ensure_login_runs_login_when_needed(monkeypatch):
    auth = _make_login()
    monkeypatch.setattr(_hub_auth, "_auth", auth)
    token = _hub_auth.ensure_login(timeout=30)
    assert token == "acc"
    assert auth("login").login_calls == 1


def test_ensure_login_rejects_env_api_key(monkeypatch):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    monkeypatch.setattr(
        _hub_auth, "_auth", _make_login(credentials=lambda: {"X-API-Key": "x"})
    )
    with pytest.raises(click.ClickException):
        _hub_auth.ensure_login()


def test_auth_kind_none_when_headers_have_no_known_key(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    monkeypatch.setattr(_hub_auth, "_auth", _make_login(credentials=lambda: {}))
    assert _hub_auth.auth_kind() == "none"


def test_auth_kind_api_key_from_header(monkeypatch):
    monkeypatch.setattr(
        _hub_auth, "_auth", _make_login(credentials=lambda: {"X-API-Key": "x"})
    )
    assert _hub_auth.auth_kind() == "api_key"


def test_bearer_token_none_without_credentials(monkeypatch):
    monkeypatch.setattr(_hub_auth, "_auth", _make_login())
    assert _hub_auth.bearer_token() is None


def test_bearer_token_none_when_not_a_bearer(monkeypatch):
    monkeypatch.setattr(
        _hub_auth, "_auth", _make_login(credentials=lambda: {"X-API-Key": "x"})
    )
    assert _hub_auth.bearer_token() is None


def test_ensure_login_skips_login_when_already_authenticated(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    auth = _make_login(credentials=_TokenCreds("tok"))
    monkeypatch.setattr(_hub_auth, "_auth", auth)
    assert _hub_auth.ensure_login() == "tok"
    assert auth("login").login_calls == 0


def test_ensure_login_raises_when_token_missing(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    # Credentials present but with no bearer token: auth_kind is "none",
    # login is skipped, and bearer_token() returns None.
    monkeypatch.setattr(
        _hub_auth, "_auth", _make_login(credentials=lambda: {"Cookie": "x"})
    )
    with pytest.raises(click.ClickException, match="not logged in"):
        _hub_auth.ensure_login()


def test_clear_login_returns_false_without_session(monkeypatch):
    monkeypatch.setattr(_hub_auth, "_auth", _make_login())
    assert _hub_auth.clear_login() is False


def test_clear_login_drops_session(monkeypatch):
    auth = _make_login(credentials=_TokenCreds("tok"))
    monkeypatch.setattr(_hub_auth, "_auth", auth)
    assert _hub_auth.clear_login() is True
    assert auth("login").credentials is None
