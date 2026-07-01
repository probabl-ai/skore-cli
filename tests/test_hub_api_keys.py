"""Tests for ``skore hub api-key`` (client + create/list/revoke commands).

The client functions are exercised against an in-memory ``httpx.MockTransport``
(no network). The command callbacks are exercised via ``CliRunner`` with the
``_client`` functions and ``require_login_token`` monkeypatched, plus a fake
Textual app for the interactive paths (mirroring the skills CLI tests).
"""

from __future__ import annotations

import json
from datetime import UTC
from types import SimpleNamespace

import httpx
import pytest
import rich_click as click
from click.testing import CliRunner

from skore_cli.hub import _api_keys, _client
from skore_cli.hub._client import ApiKeyInfo, Membership


def _transport(handler):
    return httpx.MockTransport(handler)


# --------------------------------------------------------------------------- #
# _client: require_login_token gate
# --------------------------------------------------------------------------- #


def test_require_login_token_errors_without_token(monkeypatch):
    monkeypatch.setattr(_client, "ensure_login", lambda: (_ for _ in ()).throw(
        click.ClickException("not logged in")
    ))
    with pytest.raises(click.ClickException) as exc:
        _client.require_login_token()
    assert "not logged in" in str(exc.value)


def test_require_login_token_returns_access_token(monkeypatch):
    monkeypatch.setattr(_client, "ensure_login", lambda: "abc")
    assert _client.require_login_token() == "abc"


# --------------------------------------------------------------------------- #
# _client: HTTP calls via MockTransport
# --------------------------------------------------------------------------- #


def test_me_parses_id_and_memberships():
    def handler(request):
        assert request.url.path == "/identity/users/me"
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(
            200,
            json={
                "id": "user-1",
                "workspace_memberships": [
                    {
                        "workspace_id": 7,
                        "public_id": "ws-a",
                        "role": "admin",
                        "permissions": ["read:project", "create:project"],
                    }
                ],
            },
        )

    user_id, memberships = _client.me(
        "http://hub.test", "tok", transport=_transport(handler)
    )
    assert user_id == "user-1"
    assert memberships == [
        Membership(7, "ws-a", frozenset({"read:project", "create:project"}))
    ]


def test_create_sends_body_and_returns_secret():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"api_key_id": 42, "api_key": "uid:secret"})

    key_id, secret = _client.create_api_key(
        "http://hub.test",
        "tok",
        "user-1",
        name="laptop",
        permissions=["read:project"],
        workspace_id=7,
        expires_at="2026-09-19T00:00:00+00:00",
        transport=_transport(handler),
    )
    assert (key_id, secret) == (42, "uid:secret")
    assert seen["path"] == "/identity/users/user-1/api-keys"
    assert seen["body"] == {
        "name": "laptop",
        "permissions": ["read:project"],
        "workspace_id": 7,
        "expires_at": "2026-09-19T00:00:00+00:00",
    }


def test_create_omits_expires_at_when_never():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"api_key_id": 1, "api_key": "k"})

    _client.create_api_key(
        "http://hub.test",
        "tok",
        "u",
        name="n",
        permissions=["read:project"],
        workspace_id=1,
        expires_at=None,
        transport=_transport(handler),
    )
    assert "expires_at" not in seen["body"]


def test_list_api_keys_parses():
    def handler(request):
        assert request.url.path == "/identity/users/u/api-keys"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "a",
                    "workspace_id": 7,
                    "created_at": "2026-01-01T00:00:00Z",
                    "expires_at": None,
                }
            ],
        )

    keys = _client.list_api_keys(
        "http://hub.test", "tok", "u", transport=_transport(handler)
    )
    assert keys == [ApiKeyInfo(1, "a", 7, "2026-01-01T00:00:00Z", None)]


def test_delete_api_key_ok():
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.path == "/identity/users/u/api-keys/5"
        return httpx.Response(204)

    _client.delete_api_key(
        "http://hub.test", "tok", "u", 5, transport=_transport(handler)
    )


@pytest.mark.parametrize(
    "code,snippet",
    [
        (401, "skore hub login"),
        (403, "not allowed"),
        (404, "not found"),
        (500, "hub request failed"),
    ],
)
def test_error_mapping(code, snippet):
    def handler(request):
        return httpx.Response(code, json={"detail": "nope"})

    with pytest.raises(click.ClickException) as exc:
        _client.list_api_keys(
            "http://hub.test", "tok", "u", transport=_transport(handler)
        )
    assert snippet in str(exc.value)


# --------------------------------------------------------------------------- #
# helpers for command tests
# --------------------------------------------------------------------------- #


def _patch_session(monkeypatch, memberships, *, user_id="user-1"):
    monkeypatch.setattr(_api_keys, "resolve_hub_uri", lambda url, *a, **k: url or "h")
    monkeypatch.setattr(_client, "require_login_token", lambda: "tok")
    monkeypatch.setattr(_client, "me", lambda uri, token: (user_id, memberships))


_WS_A = Membership(7, "ws-a", frozenset({"read:project", "create:project"}))


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #


def test_create_requires_login(monkeypatch):
    monkeypatch.setattr(_api_keys, "resolve_hub_uri", lambda url, *a, **k: "h")

    def boom():
        raise click.ClickException("not logged in; run `skore hub login` first.")

    monkeypatch.setattr(_client, "require_login_token", boom)

    result = CliRunner().invoke(
        _api_keys.api_key, ["create", "-w", "ws-a", "--name", "x", "-p", "read:project"]
    )
    assert result.exit_code != 0
    assert "not logged in" in result.output


def test_create_non_interactive_builds_payload(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: False)
    captured = {}

    def fake_create(
        uri, token, user_id, *, name, permissions, workspace_id, expires_at
    ):
        captured.update(
            user_id=user_id,
            name=name,
            permissions=permissions,
            workspace_id=workspace_id,
            expires_at=expires_at,
        )
        return 42, "uid:secret"

    monkeypatch.setattr(_client, "create_api_key", fake_create)

    result = CliRunner().invoke(
        _api_keys.api_key,
        [
            "create",
            "--hub-url",
            "http://hub.test",
            "-w",
            "ws-a",
            "--name",
            "laptop",
            "-p",
            "read:project",
            "--validity",
            "never",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "uid:secret" in result.output
    assert captured == {
        "user_id": "user-1",
        "name": "laptop",
        "permissions": ["read:project"],
        "workspace_id": 7,
        "expires_at": None,
    }


def test_create_requires_workspace(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: False)

    result = CliRunner().invoke(
        _api_keys.api_key, ["create", "--name", "x", "-p", "read:project"]
    )
    assert result.exit_code != 0
    assert "--workspace" in result.output


def test_create_unknown_workspace_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: False)

    result = CliRunner().invoke(
        _api_keys.api_key,
        ["create", "-w", "nope", "--name", "x", "-p", "read:project"],
    )
    assert result.exit_code != 0
    assert "unknown workspace" in result.output


def test_create_rejects_ungranted_permission(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: False)

    result = CliRunner().invoke(
        _api_keys.api_key,
        ["create", "-w", "ws-a", "--name", "x", "-p", "delete:project"],
    )
    assert result.exit_code != 0
    assert "cannot grant delete:project" in result.output


def test_create_interactive_uses_form(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: True)

    class _FakeForm:
        def __init__(self, *a, **k):
            self.result = hub_app.ApiKeyFormResult(
                name="laptop",
                workspace_id=7,
                workspace_public_id="ws-a",
                permissions=["read:project"],
                validity="never",
            )

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "ApiKeyForm", _FakeForm)

    captured = {}

    def fake_create(
        uri, token, user_id, *, name, permissions, workspace_id, expires_at
    ):
        captured.update(name=name, workspace_id=workspace_id, expires_at=expires_at)
        return 7, "uid:secret"

    monkeypatch.setattr(_client, "create_api_key", fake_create)

    # No -w/-p flags => interactive form path.
    result = CliRunner().invoke(_api_keys.api_key, ["create"])
    assert result.exit_code == 0, result.output
    assert "uid:secret" in result.output
    assert captured == {"name": "laptop", "workspace_id": 7, "expires_at": None}


def test_create_interactive_cancel(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: True)

    class _FakeForm:
        def __init__(self, *a, **k):
            self.result = None

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "ApiKeyForm", _FakeForm)
    monkeypatch.setattr(
        _client,
        "create_api_key",
        lambda *a, **k: pytest.fail("create should not be called on cancel"),
    )

    result = CliRunner().invoke(_api_keys.api_key, ["create"])
    assert result.exit_code == 0, result.output
    assert "Nothing created" in result.output


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_list_prints_table(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(
        _client,
        "list_api_keys",
        lambda uri, token, user_id: [
            ApiKeyInfo(1, "laptop", 7, "2026-01-01T00:00:00Z", None)
        ],
    )

    result = CliRunner().invoke(_api_keys.api_key, ["list", "--hub-url", "http://h"])
    assert result.exit_code == 0, result.output
    assert "laptop" in result.output
    assert "ws-a" in result.output
    assert "never" in result.output


def test_list_empty(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_client, "list_api_keys", lambda uri, token, user_id: [])

    result = CliRunner().invoke(_api_keys.api_key, ["list"])
    assert result.exit_code == 0, result.output
    assert "No API keys" in result.output


# --------------------------------------------------------------------------- #
# revoke
# --------------------------------------------------------------------------- #


def test_revoke_by_id(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    deleted = {}
    monkeypatch.setattr(
        _client,
        "delete_api_key",
        lambda uri, token, user_id, api_key_id: deleted.update(id=api_key_id),
    )

    result = CliRunner().invoke(
        _api_keys.api_key, ["revoke", "--hub-url", "http://h", "--id", "5", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert deleted["id"] == 5
    assert "revoked API key 5" in result.output


def test_revoke_non_interactive_without_id_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: False)
    monkeypatch.setattr(
        _client,
        "list_api_keys",
        lambda uri, token, user_id: [ApiKeyInfo(5, "laptop", 7, None, None)],
    )

    result = CliRunner().invoke(_api_keys.api_key, ["revoke"])
    assert result.exit_code != 0
    assert "--id" in result.output


def test_revoke_interactive_picker(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_api_keys, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        _client,
        "list_api_keys",
        lambda uri, token, user_id: [ApiKeyInfo(5, "laptop", 7, None, None)],
    )

    class _FakePicker:
        def __init__(self, *a, **k):
            self.result = 5

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "IdPicker", _FakePicker)
    deleted = {}
    monkeypatch.setattr(
        _client,
        "delete_api_key",
        lambda uri, token, user_id, api_key_id: deleted.update(id=api_key_id),
    )

    result = CliRunner().invoke(_api_keys.api_key, ["revoke", "--yes"])
    assert result.exit_code == 0, result.output
    assert deleted["id"] == 5


# --------------------------------------------------------------------------- #
# _expires_at
# --------------------------------------------------------------------------- #


def test_expires_at_never_is_none():
    assert _api_keys._expires_at("never") is None


def test_expires_at_months_is_future_iso():
    from datetime import datetime

    value = _api_keys._expires_at("3")
    parsed = datetime.fromisoformat(value)
    assert parsed > datetime.now(UTC)
