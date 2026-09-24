"""Tests for the ``skore hub`` command group."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import rich_click as click
from click.testing import CliRunner
from skore._plugins.hub.authentication import registry

from skore_cli import cli
from skore_cli.hub import _client
from skore_cli.hub import _commands as _hub
from skore_cli.hub._commands import PROJECT_PERMISSIONS

pytestmark = pytest.mark.usefixtures("monkeypatch_home", "monkeypatch_keyring")


def _invoke(args: list[str]):
    return CliRunner().invoke(cli, args)


def _membership(public_id: str = "ws-1", workspace_id: int = 1):
    return _client.Membership(
        workspace_id=workspace_id,
        public_id=public_id,
        permissions=frozenset(PROJECT_PERMISSIONS),
    )


def test_hub_no_subcommand_shows_help():
    result = _invoke(["hub"])

    assert result.exit_code == 0
    assert "api-key" in result.output


def test_hub_api_key_no_subcommand_shows_help():
    result = _invoke(["hub", "api-key"])

    assert result.exit_code == 0
    assert "generate" in result.output
    assert "delete" in result.output
    assert "list" in result.output


def test_hub_api_key_delete_requires_workspace():
    result = _invoke(["hub", "api-key", "delete"])

    assert result.exit_code != 0
    assert "workspace" in result.output.lower()


def test_hub_api_key_delete_removes_key():
    registry.set(host="http://hub.test", workspace="team", api_key="secret")

    result = _invoke(
        ["hub", "api-key", "delete", "--host=http://hub.test", "--workspace=team"]
    )

    assert result.exit_code == 0
    assert registry.get(host="http://hub.test", workspace="team") is None


def test_hub_api_key_delete_without_host_uses_environment_uri(monkeypatch):
    monkeypatch.setenv("SKORE_HUB_URI", "http://hub.test")
    registry.set(host="http://hub.test", workspace="team", api_key="secret")
    registry.set(host="http://other.test", workspace="team", api_key="other")

    result = _invoke(["hub", "api-key", "delete", "--workspace=team"])

    assert result.exit_code == 0
    assert registry.get(host="http://hub.test", workspace="team") is None
    assert registry.get(host="http://other.test", workspace="team") == "other"


def test_hub_api_key_list_empty():
    result = _invoke(["hub", "api-key", "list"])

    assert result.exit_code == 0
    assert "No API keys stored." in result.output


def test_hub_api_key_list_shows_host_and_workspace():
    registry.set(host="http://a.test", workspace="w1", api_key="k1")
    registry.set(host="http://b.test", workspace="w2", api_key="k2")

    result = _invoke(["hub", "api-key", "list"])

    assert result.exit_code == 0
    assert "http://a.test" in result.output
    assert "w1" in result.output
    assert "http://b.test" in result.output
    assert "w2" in result.output
    assert "k1" not in result.output
    assert "k2" not in result.output


def test_resolve_api_key_name_deduplicates():
    assert _hub._resolve_api_key_name("opencode", []) == "opencode"
    assert _hub._resolve_api_key_name("opencode", ["opencode"]) == "opencode-2"
    assert (
        _hub._resolve_api_key_name("opencode", ["opencode", "opencode-2"])
        == "opencode-3"
    )


def test_create_workspace_api_key_mints_secret(monkeypatch):
    monkeypatch.setattr(_hub._client, "list_api_keys", lambda *a, **k: [])
    captured = {}

    def fake_create(hub_url, token, user_id, **kwargs):
        captured.update(kwargs)
        return 7, "the-secret"

    monkeypatch.setattr(_hub._client, "create_api_key", fake_create)

    secret = _hub._create_workspace_api_key(
        "http://hub.test", "tok", "user-1", _membership(), "opencode"
    )

    assert secret == "the-secret"
    assert captured["name"] == "opencode"
    assert captured["expires_at"] is None
    assert set(captured["permissions"]) == set(PROJECT_PERMISSIONS)


def test_create_workspace_api_key_requires_permissions():
    membership = _client.Membership(
        workspace_id=1, public_id="ws-1", permissions=frozenset()
    )
    with pytest.raises(click.ClickException, match="cannot create project API keys"):
        _hub._create_workspace_api_key(
            "http://hub.test", "tok", "user-1", membership, "opencode"
        )


def test_create_workspace_api_key_dedupes_name_within_workspace(monkeypatch):
    existing = [
        _client.ApiKeyInfo(
            id=1,
            name="opencode",
            workspace_id=1,
            created_at=None,
            expires_at=None,
        )
    ]
    monkeypatch.setattr(_hub._client, "list_api_keys", lambda *a, **k: existing)
    captured = {}

    def fake_create(hub_url, token, user_id, **kwargs):
        captured.update(kwargs)
        return 2, "secret"

    monkeypatch.setattr(_hub._client, "create_api_key", fake_create)

    _hub._create_workspace_api_key(
        "http://hub.test", "tok", "user-1", _membership(), "opencode"
    )

    assert captured["name"] == "opencode-2"


def test_expires_at_from_months_clamps_end_of_month():
    now = datetime(2026, 1, 31, 12, 0, 0, tzinfo=timezone.utc)
    assert _hub._expires_at_from_months(1, now=now) == "2026-02-28T12:00:00Z"
    assert _hub._expires_at_from_months(3, now=now) == "2026-04-30T12:00:00Z"


def test_expires_at_from_choice_never_is_none():
    assert _hub._expires_at_from_choice("never") is None


def test_hub_api_key_generate_requires_workspace():
    result = _invoke(["hub", "api-key", "generate"])

    assert result.exit_code != 0
    assert "workspace" in result.output.lower()


def test_hub_api_key_generate_stores_key(monkeypatch):
    monkeypatch.setattr(_hub, "_host", lambda host: host or "http://hub.test")
    monkeypatch.setattr(_hub, "login", lambda *, timeout: SimpleNamespace(access="tok"))
    monkeypatch.setattr(
        _hub._client, "me", lambda hub_url, token: ("user-1", [_membership("team")])
    )
    monkeypatch.setattr(_hub._client, "list_api_keys", lambda *a, **k: [])
    captured = {}

    def fake_create(*a, **k):
        captured.update(k)
        return 42, "minted-secret"

    monkeypatch.setattr(_hub._client, "create_api_key", fake_create)

    result = _invoke(["hub", "api-key", "generate", "--workspace=team"])

    assert result.exit_code == 0, result.output
    assert registry.get(host="http://hub.test", workspace="team") == "minted-secret"
    assert captured["expires_at"] is None
    assert "expires " not in result.output


def test_hub_api_key_generate_expires_in_three_months(monkeypatch):
    now = datetime(2026, 1, 15, 8, 30, 0, tzinfo=timezone.utc)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(_hub, "_host", lambda host: host or "http://hub.test")
    monkeypatch.setattr(_hub, "login", lambda *, timeout: SimpleNamespace(access="tok"))
    monkeypatch.setattr(
        _hub._client, "me", lambda hub_url, token: ("user-1", [_membership("team")])
    )
    monkeypatch.setattr(_hub._client, "list_api_keys", lambda *a, **k: [])
    captured = {}

    def fake_create(*a, **k):
        captured.update(k)
        return 42, "minted-secret"

    monkeypatch.setattr(_hub._client, "create_api_key", fake_create)
    monkeypatch.setattr(_hub, "datetime", _FrozenDateTime)

    result = _invoke(
        ["hub", "api-key", "generate", "--workspace=team", "--expires", "3"]
    )

    assert result.exit_code == 0, result.output
    assert captured["expires_at"] == "2026-04-15T08:30:00Z"
    assert "expires 2026-04-15T08:30:00Z" in result.output


def test_hub_api_key_generate_rejects_unknown_expires(monkeypatch):
    result = _invoke(
        ["hub", "api-key", "generate", "--workspace=team", "--expires", "12"]
    )

    assert result.exit_code != 0
    assert "expires" in result.output.lower()


def test_hub_api_key_generate_unknown_workspace(monkeypatch):
    monkeypatch.setattr(_hub, "_host", lambda host: host or "http://hub.test")
    monkeypatch.setattr(_hub, "login", lambda *, timeout: SimpleNamespace(access="tok"))
    monkeypatch.setattr(
        _hub._client, "me", lambda hub_url, token: ("user-1", [_membership("team")])
    )

    result = _invoke(["hub", "api-key", "generate", "--workspace=other"])

    assert result.exit_code != 0
    assert "not in your memberships" in result.output
