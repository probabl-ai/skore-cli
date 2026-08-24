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
    assert _hub_auth.api_key_from_env() == "uid:secret"


def test_api_key_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    assert _hub_auth.api_key_from_env() is None


def test_ensure_bearer_token_runs_login_when_needed(monkeypatch):
    auth = _make_login()
    monkeypatch.setattr(_hub_auth, "_auth", auth)
    token = _hub_auth.ensure_bearer_token(timeout=30)
    assert token == "acc"
    assert auth("login").login_calls == 1


def test_ensure_bearer_token_rejects_env_api_key(monkeypatch):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    with pytest.raises(click.ClickException, match="unset it"):
        _hub_auth.ensure_bearer_token()


def test_ensure_bearer_token_reuses_existing_token(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    auth = _make_login(credentials=_TokenCreds("tok"))
    monkeypatch.setattr(_hub_auth, "_auth", auth)
    assert _hub_auth.ensure_bearer_token() == "tok"
    assert auth("login").login_calls == 0


def test_ensure_bearer_token_raises_when_token_missing(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    monkeypatch.setattr(
        _hub_auth, "_auth", _make_login(credentials=lambda: {"Cookie": "x"})
    )
    with pytest.raises(click.ClickException, match="bearer token"):
        _hub_auth.ensure_bearer_token()
