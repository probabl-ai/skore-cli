"""Tests for the ``skore hub`` command group (login/logout/status).

The hub commands reach into the optional ``skore`` package through the module
level ``_auth`` accessor. ``skore`` is not installed in the test environment, so
every test swaps ``_auth`` for an in-memory fake -- this keeps the tests fast and
hermetic while exercising the real command logic.
"""

from __future__ import annotations

from types import SimpleNamespace

import importlib

import pytest
from click.testing import CliRunner

# ``skore_cli.__init__`` rebinds the ``hub`` attribute to the command group, which
# shadows the submodule for ``import skore_cli.hub as hub``; fetch the real module
# from ``sys.modules`` so we can monkeypatch its ``_auth`` accessor.
hub = importlib.import_module("skore_cli.hub")
hub_cli = hub.hub


class _Recorder:
    def __init__(self, token):
        self.token = dict(token) if token else None
        self.saved = None
        self.cleared = False
        self.logout_args = None
        self.interactive_called = False
        self.logout_error = None


def _make_auth(recorder: _Recorder, *, uri="http://hub.test", expired=False):
    def interactive_device_login(*, timeout=600):
        recorder.interactive_called = True
        return ("acc", "ref", "2099-01-01T00:00:00+00:00")

    def post_oauth_logout(access_token, refresh_token=None):
        recorder.logout_args = (access_token, refresh_token)
        if recorder.logout_error is not None:
            raise recorder.logout_error

    def save(token):
        recorder.saved = token
        return "/tmp/hub.json"

    def clear():
        if recorder.token:
            recorder.cleared = True
            recorder.token = None
            return "/tmp/hub.json"
        return None

    store = SimpleNamespace(
        load=lambda: recorder.token,
        save=save,
        clear=clear,
        path=lambda: "/tmp/hub.json",
    )
    token_mod = SimpleNamespace(
        interactive_device_login=interactive_device_login,
        post_oauth_logout=post_oauth_logout,
        _token_expired=lambda expires_at: expired,
    )
    uri_mod = SimpleNamespace(URI=lambda: uri)

    modules = {"uri": uri_mod, "store": store, "token": token_mod}
    return lambda name: modules[name]


@pytest.fixture
def no_api_key(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    monkeypatch.delenv("SKORE_HUB_URI", raising=False)


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


def test_status_with_api_key(monkeypatch, no_api_key):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    monkeypatch.setattr(hub, "_auth", _make_auth(_Recorder(None)))

    result = CliRunner().invoke(hub_cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "set" in result.output


def test_status_with_valid_token(monkeypatch, no_api_key):
    recorder = _Recorder({"access_token": "acc", "expires_at": "2099-01-01"})
    monkeypatch.setattr(hub, "_auth", _make_auth(recorder, expired=False))

    result = CliRunner().invoke(hub_cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_status_with_expired_token(monkeypatch, no_api_key):
    recorder = _Recorder({"access_token": "acc", "expires_at": "2000-01-01"})
    monkeypatch.setattr(hub, "_auth", _make_auth(recorder, expired=True))

    result = CliRunner().invoke(hub_cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "expired" in result.output


def test_status_unauthenticated_errors(monkeypatch, no_api_key):
    monkeypatch.setattr(hub, "_auth", _make_auth(_Recorder(None)))

    result = CliRunner().invoke(hub_cli, ["status"])

    assert result.exit_code != 0
    assert "Not authenticated" in result.output


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #


def test_login_with_api_key_does_nothing(monkeypatch, no_api_key):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    recorder = _Recorder(None)
    monkeypatch.setattr(hub, "_auth", _make_auth(recorder))

    result = CliRunner().invoke(hub_cli, ["login"])

    assert result.exit_code == 0, result.output
    assert recorder.interactive_called is False
    assert recorder.saved is None


def test_login_without_key_runs_device_flow(monkeypatch, no_api_key):
    recorder = _Recorder(None)
    monkeypatch.setattr(hub, "_auth", _make_auth(recorder))

    result = CliRunner().invoke(hub_cli, ["login"])

    assert result.exit_code == 0, result.output
    assert recorder.interactive_called is True
    assert recorder.saved == {
        "uri": "http://hub.test",
        "access_token": "acc",
        "refresh_token": "ref",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }


def test_login_hub_url_sets_env(monkeypatch, no_api_key):
    recorder = _Recorder(None)
    # URI() echoes the env var the command is expected to set from --hub-url.
    monkeypatch.setattr(
        hub, "_auth", _make_auth(recorder, uri="http://127.0.0.1:9999")
    )

    result = CliRunner().invoke(hub_cli, ["login", "--hub-url", "http://127.0.0.1:9999"])

    assert result.exit_code == 0, result.output
    import os

    assert os.environ.get("SKORE_HUB_URI") == "http://127.0.0.1:9999"


# --------------------------------------------------------------------------- #
# logout
# --------------------------------------------------------------------------- #


def test_logout_revokes_and_clears(monkeypatch, no_api_key):
    recorder = _Recorder({"access_token": "acc", "refresh_token": "ref"})
    monkeypatch.setattr(hub, "_auth", _make_auth(recorder))

    result = CliRunner().invoke(hub_cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert recorder.logout_args == ("acc", "ref")
    assert recorder.cleared is True
    assert "revoked the token" in result.output


def test_logout_still_clears_when_revoke_fails(monkeypatch, no_api_key):
    recorder = _Recorder({"access_token": "acc", "refresh_token": "ref"})
    recorder.logout_error = RuntimeError("network down")
    monkeypatch.setattr(hub, "_auth", _make_auth(recorder))

    result = CliRunner().invoke(hub_cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert recorder.cleared is True
    assert "Could not revoke" in result.output


def test_logout_no_token_with_api_key(monkeypatch, no_api_key):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    monkeypatch.setattr(hub, "_auth", _make_auth(_Recorder(None)))

    result = CliRunner().invoke(hub_cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert "user-managed" in result.output


def test_logout_no_token_at_all(monkeypatch, no_api_key):
    monkeypatch.setattr(hub, "_auth", _make_auth(_Recorder(None)))

    result = CliRunner().invoke(hub_cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert "No stored token to remove" in result.output
