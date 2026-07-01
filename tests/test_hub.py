"""Tests for the ``skore hub`` command group (login/logout/status)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from skore_cli import _hub_auth
from skore_cli.hub import _commands as hub

hub_cli = hub.hub


class _TokenCreds:
    def __init__(self, token: str = "acc"):
        self._token = token

    def __call__(self):
        return {"Authorization": f"Bearer {self._token}"}


def _make_login(*, credentials=None, uri="http://hub.test"):
    login_mod = SimpleNamespace(credentials=credentials, login_calls=0)

    def login(*, timeout=600):
        login_mod.login_calls += 1
        login_mod.credentials = _TokenCreds()

    login_mod.login = login
    uri_mod = SimpleNamespace(URI=lambda: uri)
    return lambda name: login_mod if name == "login" else uri_mod


def _patch_auth(monkeypatch, auth_fn):
    monkeypatch.setattr(_hub_auth, "_auth", auth_fn)
    monkeypatch.setattr(hub, "_auth", auth_fn)


@pytest.fixture
def no_api_key(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    monkeypatch.delenv("SKORE_HUB_URI", raising=False)


def test_status_with_api_key(monkeypatch, no_api_key):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    _patch_auth(monkeypatch, _make_login())

    result = CliRunner().invoke(hub_cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "API key" in result.output


def test_status_with_interactive_session(monkeypatch, no_api_key):
    _patch_auth(monkeypatch, _make_login(credentials=_TokenCreds()))

    result = CliRunner().invoke(hub_cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "interactive token" in result.output


def test_status_unauthenticated_errors(monkeypatch, no_api_key):
    _patch_auth(monkeypatch, _make_login())

    result = CliRunner().invoke(hub_cli, ["status"])

    assert result.exit_code != 0
    assert "Not authenticated" in result.output


def test_login_with_api_key_does_nothing(monkeypatch, no_api_key):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    auth = _make_login()
    _patch_auth(monkeypatch, auth)

    result = CliRunner().invoke(hub_cli, ["login"])

    assert result.exit_code == 0, result.output
    assert auth("login").login_calls == 0


def test_login_without_key_runs_device_flow(monkeypatch, no_api_key):
    auth = _make_login()
    _patch_auth(monkeypatch, auth)

    result = CliRunner().invoke(hub_cli, ["login"])

    assert result.exit_code == 0, result.output
    assert auth("login").login_calls == 1
    assert auth("login").credentials is not None


def test_login_hub_url_sets_env(monkeypatch, no_api_key):
    _patch_auth(monkeypatch, _make_login(uri="http://127.0.0.1:9999"))

    result = CliRunner().invoke(
        hub_cli, ["login", "--hub-url", "http://127.0.0.1:9999"]
    )

    assert result.exit_code == 0, result.output
    import os

    assert os.environ.get("SKORE_HUB_URI") == "http://127.0.0.1:9999"


def test_resolve_hub_uri_seeds_env_and_resolves(no_api_key):
    import os

    from skore_cli import _skore

    seen = {}

    def fake_auth(name):
        seen["name"] = name
        return SimpleNamespace(URI=lambda: "http://resolved")

    uri = _skore.resolve_hub_uri("http://127.0.0.1:8000", fake_auth)

    assert seen["name"] == "uri"
    assert os.environ.get("SKORE_HUB_URI") == "http://127.0.0.1:8000"
    assert uri == "http://resolved"


def test_resolve_hub_uri_without_url_leaves_env(no_api_key):
    import os

    from skore_cli import _skore

    uri = _skore.resolve_hub_uri(
        None, lambda name: SimpleNamespace(URI=lambda: "http://default")
    )

    assert "SKORE_HUB_URI" not in os.environ
    assert uri == "http://default"


def test_logout_clears_session(monkeypatch, no_api_key):
    auth = _make_login(credentials=_TokenCreds())
    _patch_auth(monkeypatch, auth)

    result = CliRunner().invoke(hub_cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert auth("login").credentials is None
    assert "cleared" in result.output


def test_logout_no_session_with_api_key(monkeypatch, no_api_key):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    _patch_auth(monkeypatch, _make_login())

    result = CliRunner().invoke(hub_cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert "user-managed" in result.output


def test_logout_no_session_at_all(monkeypatch, no_api_key):
    _patch_auth(monkeypatch, _make_login())

    result = CliRunner().invoke(hub_cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert "No interactive session" in result.output
