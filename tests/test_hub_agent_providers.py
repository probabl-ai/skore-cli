"""Tests for ``skore hub agent-provider`` (client + add/list/activate/remove).

The client functions are exercised against an in-memory ``httpx.MockTransport``
(no network). The command callbacks are exercised via ``CliRunner`` with the
``_client`` functions and the session helpers monkeypatched, plus fake Textual
apps for the interactive paths (mirroring the api-key tests).
"""

from __future__ import annotations

import json

import httpx
import pytest
import rich_click as click
from click.testing import CliRunner

from skore_cli.hub import _agent_providers, _api_keys, _client
from skore_cli.hub._client import AgentProviders, Membership, ProviderEntry


def _transport(handler):
    return httpx.MockTransport(handler)


def _entry(**overrides):
    base = {
        "id": 11,
        "name": "team",
        "is_active": False,
        "provider": "skore",
        "selected_model": None,
        "aws_region": None,
        "bedrock_role_arn": None,
        "anthropic_api_key_set": False,
        "bedrock_external_id_set": False,
        "aws_access_key_id_set": False,
        "aws_secret_access_key_set": False,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# _client: HTTP calls via MockTransport
# --------------------------------------------------------------------------- #


def test_agent_providers_parses():
    def handler(request):
        assert request.url.path == "/agent/workspaces/7/providers"
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(
            200,
            json={
                "providers": [
                    _entry(
                        id=1,
                        name="byo",
                        is_active=True,
                        provider="anthropic",
                        selected_model="claude-x",
                        anthropic_api_key_set=True,
                    )
                ],
                "available_models": {"anthropic": ["claude-x"], "bedrock": ["nova"]},
                "encryption_configured": True,
            },
        )

    result = _client.agent_providers(
        "http://hub.test", "tok", 7, transport=_transport(handler)
    )
    assert result == AgentProviders(
        providers=[
            ProviderEntry(
                id=1,
                name="byo",
                is_active=True,
                provider="anthropic",
                selected_model="claude-x",
                aws_region=None,
                bedrock_role_arn=None,
                anthropic_api_key_set=True,
                bedrock_external_id_set=False,
                aws_access_key_id_set=False,
                aws_secret_access_key_set=False,
            )
        ],
        available_models={"anthropic": ["claude-x"], "bedrock": ["nova"]},
        encryption_configured=True,
    )


def test_create_agent_provider_posts_body_and_returns_entry():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json=_entry(id=42, name="team", provider="anthropic", selected_model="cx"),
        )

    entry = _client.create_agent_provider(
        "http://hub.test",
        "tok",
        7,
        payload={"name": "team", "provider": "anthropic", "selected_model": "cx"},
        transport=_transport(handler),
    )
    assert entry.id == 42
    assert seen["path"] == "/agent/workspaces/7/providers"
    assert seen["body"] == {
        "name": "team",
        "provider": "anthropic",
        "selected_model": "cx",
    }


def test_activate_agent_provider_hits_path():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/agent/workspaces/7/providers/3/activate"
        return httpx.Response(204)

    _client.activate_agent_provider(
        "http://hub.test", "tok", 7, 3, transport=_transport(handler)
    )


def test_delete_agent_provider_hits_path():
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.path == "/agent/workspaces/7/providers/3"
        return httpx.Response(204)

    _client.delete_agent_provider(
        "http://hub.test", "tok", 7, 3, transport=_transport(handler)
    )


def test_create_403_maps_to_owner_admin_message():
    def handler(request):
        return httpx.Response(403, json={"detail": "forbidden"})

    with pytest.raises(click.ClickException) as exc:
        _client.create_agent_provider(
            "http://hub.test", "tok", 7, payload={}, transport=_transport(handler)
        )
    assert "owner/admin" in str(exc.value)


def test_create_400_surfaces_detail():
    def handler(request):
        return httpx.Response(400, json={"detail": "encryption not configured"})

    with pytest.raises(click.ClickException) as exc:
        _client.create_agent_provider(
            "http://hub.test", "tok", 7, payload={}, transport=_transport(handler)
        )
    assert "encryption not configured" in str(exc.value)


# --------------------------------------------------------------------------- #
# helpers for command tests
# --------------------------------------------------------------------------- #


def _patch_session(monkeypatch, memberships, *, user_id="user-1"):
    monkeypatch.setattr(_api_keys, "resolve_hub_uri", lambda url, *a, **k: url or "h")
    monkeypatch.setattr(_client, "require_login_token", lambda: "tok")
    monkeypatch.setattr(_client, "me", lambda uri, token: (user_id, memberships))


def _patch_providers(
    monkeypatch, *, providers=None, available_models=None, encryption=False
):
    value = AgentProviders(
        providers=providers or [],
        available_models=available_models or {},
        encryption_configured=encryption,
    )
    monkeypatch.setattr(_client, "agent_providers", lambda uri, token, ws_id: value)
    return value


_WS_A = Membership(7, "ws-a", frozenset())
_WS_B = Membership(8, "ws-b", frozenset())


# --------------------------------------------------------------------------- #
# add
# --------------------------------------------------------------------------- #


def test_add_requires_login(monkeypatch):
    monkeypatch.setattr(_api_keys, "resolve_hub_uri", lambda url, *a, **k: "h")

    def boom():
        raise click.ClickException("not logged in; run `skore hub login` first.")

    monkeypatch.setattr(_client, "require_login_token", boom)

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        ["add", "-w", "ws-a", "--name", "x", "--provider", "skore"],
    )
    assert result.exit_code != 0
    assert "not logged in" in result.output


def test_add_unknown_workspace_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(monkeypatch)

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        ["add", "-w", "nope", "--name", "x", "--provider", "skore"],
    )
    assert result.exit_code != 0
    assert "unknown workspace" in result.output


def test_add_multi_workspace_non_interactive_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A, _WS_B])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(monkeypatch)

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        ["add", "--name", "x", "--provider", "skore"],
    )
    assert result.exit_code != 0
    assert "--workspace" in result.output


def test_add_skore_builds_name_only_payload(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(monkeypatch)
    captured = {}

    def fake_create(uri, token, ws_id, *, payload):
        captured.update(ws_id=ws_id, payload=payload)
        return ProviderEntry(
            11, "team", False, "skore", None, None, None, False, False, False, False
        )

    monkeypatch.setattr(_client, "create_agent_provider", fake_create)
    monkeypatch.setattr(
        _client,
        "activate_agent_provider",
        lambda *a, **k: pytest.fail("should not activate"),
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        ["add", "--name", "team", "--provider", "skore"],
    )
    assert result.exit_code == 0, result.output
    assert captured["ws_id"] == 7
    assert captured["payload"] == {"name": "team", "provider": "skore"}


def test_add_anthropic_payload_and_activate(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(
        monkeypatch, available_models={"anthropic": ["claude-x"]}, encryption=True
    )
    captured = {}

    def fake_create(uri, token, ws_id, *, payload):
        captured["payload"] = payload
        return ProviderEntry(
            12,
            "team",
            False,
            "anthropic",
            "claude-x",
            None,
            None,
            True,
            False,
            False,
            False,
        )

    activated = {}
    monkeypatch.setattr(_client, "create_agent_provider", fake_create)
    monkeypatch.setattr(
        _client,
        "activate_agent_provider",
        lambda uri, token, ws_id, cid: activated.update(ws_id=ws_id, id=cid),
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        [
            "add",
            "-w",
            "ws-a",
            "--name",
            "team",
            "--provider",
            "anthropic",
            "--model",
            "claude-x",
            "--anthropic-api-key",
            "secret",
            "--activate",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["payload"] == {
        "name": "team",
        "provider": "anthropic",
        "selected_model": "claude-x",
        "anthropic_api_key": "secret",
    }
    assert activated == {"ws_id": 7, "id": 12}


def test_add_bedrock_optional_fields(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(
        monkeypatch, available_models={"bedrock": ["nova"]}, encryption=True
    )
    captured = {}

    def fake_create(uri, token, ws_id, *, payload):
        captured["payload"] = payload
        return ProviderEntry(
            13,
            "team",
            False,
            "bedrock",
            "nova",
            "us-east-1",
            None,
            False,
            False,
            False,
            False,
        )

    monkeypatch.setattr(_client, "create_agent_provider", fake_create)

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        [
            "add",
            "-w",
            "ws-a",
            "--name",
            "team",
            "--provider",
            "bedrock",
            "--model",
            "nova",
            "--aws-region",
            "us-east-1",
            "--bedrock-role-arn",
            "arn:aws:iam::1:role/x",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["payload"] == {
        "name": "team",
        "provider": "bedrock",
        "selected_model": "nova",
        "aws_region": "us-east-1",
        "bedrock_role_arn": "arn:aws:iam::1:role/x",
    }


def test_add_byo_without_encryption_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(
        monkeypatch, available_models={"anthropic": ["claude-x"]}, encryption=False
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        [
            "add",
            "-w",
            "ws-a",
            "--name",
            "team",
            "--provider",
            "anthropic",
            "--model",
            "claude-x",
            "--anthropic-api-key",
            "secret",
        ],
    )
    assert result.exit_code != 0
    assert "encryption" in result.output


def test_add_model_not_available_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(
        monkeypatch, available_models={"anthropic": ["claude-x"]}, encryption=True
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        [
            "add",
            "-w",
            "ws-a",
            "--name",
            "team",
            "--provider",
            "anthropic",
            "--model",
            "nope",
            "--anthropic-api-key",
            "secret",
        ],
    )
    assert result.exit_code != 0
    assert "unknown model" in result.output


def test_add_anthropic_missing_key_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(
        monkeypatch, available_models={"anthropic": ["claude-x"]}, encryption=True
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        [
            "add",
            "-w",
            "ws-a",
            "--name",
            "team",
            "--provider",
            "anthropic",
            "--model",
            "claude-x",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "anthropic-api-key" in result.output


def test_add_interactive_uses_form(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: True)
    _patch_providers(
        monkeypatch, available_models={"anthropic": ["claude-x"]}, encryption=True
    )

    class _FakeForm:
        def __init__(self, *a, **k):
            self.result = hub_app.AgentProviderFormResult(
                name="team",
                provider="anthropic",
                selected_model="claude-x",
                anthropic_api_key="secret",
                aws_region=None,
                bedrock_role_arn=None,
                bedrock_external_id=None,
                aws_access_key_id=None,
                aws_secret_access_key=None,
                activate=True,
            )

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "AgentProviderForm", _FakeForm)

    captured = {}

    def fake_create(uri, token, ws_id, *, payload):
        captured["payload"] = payload
        return ProviderEntry(
            14,
            "team",
            False,
            "anthropic",
            "claude-x",
            None,
            None,
            True,
            False,
            False,
            False,
        )

    activated = {}
    monkeypatch.setattr(_client, "create_agent_provider", fake_create)
    monkeypatch.setattr(
        _client,
        "activate_agent_provider",
        lambda uri, token, ws_id, cid: activated.update(id=cid),
    )

    result = CliRunner().invoke(_agent_providers.agent_provider, ["add", "-w", "ws-a"])
    assert result.exit_code == 0, result.output
    assert captured["payload"] == {
        "name": "team",
        "provider": "anthropic",
        "selected_model": "claude-x",
        "anthropic_api_key": "secret",
    }
    assert activated == {"id": 14}


def test_add_interactive_cancel(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: True)
    _patch_providers(monkeypatch)

    class _FakeForm:
        def __init__(self, *a, **k):
            self.result = None

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "AgentProviderForm", _FakeForm)
    monkeypatch.setattr(
        _client,
        "create_agent_provider",
        lambda *a, **k: pytest.fail("should not create on cancel"),
    )

    result = CliRunner().invoke(_agent_providers.agent_provider, ["add", "-w", "ws-a"])
    assert result.exit_code == 0, result.output
    assert "Nothing added" in result.output


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_list_prints_table(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    _patch_providers(
        monkeypatch,
        providers=[
            ProviderEntry(
                1,
                "byo",
                True,
                "anthropic",
                "claude-x",
                None,
                None,
                True,
                False,
                False,
                False,
            )
        ],
        encryption=True,
    )

    result = CliRunner().invoke(_agent_providers.agent_provider, ["list", "-w", "ws-a"])
    assert result.exit_code == 0, result.output
    assert "byo" in result.output
    assert "anthropic" in result.output
    assert "claude-x" in result.output


def test_list_empty_with_encryption_note(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    _patch_providers(monkeypatch, encryption=False)

    result = CliRunner().invoke(_agent_providers.agent_provider, ["list", "-w", "ws-a"])
    assert result.exit_code == 0, result.output
    assert "No agent providers" in result.output
    assert "Encryption is not configured" in result.output


# --------------------------------------------------------------------------- #
# activate
# --------------------------------------------------------------------------- #


def test_activate_by_id(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    activated = {}
    monkeypatch.setattr(
        _client,
        "activate_agent_provider",
        lambda uri, token, ws_id, cid: activated.update(id=cid),
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider, ["activate", "-w", "ws-a", "--id", "5"]
    )
    assert result.exit_code == 0, result.output
    assert activated == {"id": 5}
    assert "activated provider 5" in result.output


def test_activate_non_interactive_without_id_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: False)
    _patch_providers(
        monkeypatch,
        providers=[
            ProviderEntry(
                5, "x", False, "skore", None, None, None, False, False, False, False
            )
        ],
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider, ["activate", "-w", "ws-a"]
    )
    assert result.exit_code != 0
    assert "--id" in result.output


def test_activate_interactive_picker(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: True)
    _patch_providers(
        monkeypatch,
        providers=[
            ProviderEntry(
                5, "x", False, "skore", None, None, None, False, False, False, False
            )
        ],
    )

    class _FakePicker:
        def __init__(self, *a, **k):
            self.result = 5

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "IdPicker", _FakePicker)
    activated = {}
    monkeypatch.setattr(
        _client,
        "activate_agent_provider",
        lambda uri, token, ws_id, cid: activated.update(id=cid),
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider, ["activate", "-w", "ws-a"]
    )
    assert result.exit_code == 0, result.output
    assert activated == {"id": 5}


# --------------------------------------------------------------------------- #
# remove
# --------------------------------------------------------------------------- #


def test_remove_by_id_yes(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    deleted = {}
    monkeypatch.setattr(
        _client,
        "delete_agent_provider",
        lambda uri, token, ws_id, cid: deleted.update(id=cid),
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        ["remove", "-w", "ws-a", "--id", "5", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert deleted == {"id": 5}
    assert "removed provider 5" in result.output


def test_remove_interactive_picker(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_agent_providers, "_is_interactive", lambda: True)
    _patch_providers(
        monkeypatch,
        providers=[
            ProviderEntry(
                6, "x", False, "skore", None, None, None, False, False, False, False
            )
        ],
    )

    class _FakePicker:
        def __init__(self, *a, **k):
            self.result = 6

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "IdPicker", _FakePicker)
    deleted = {}
    monkeypatch.setattr(
        _client,
        "delete_agent_provider",
        lambda uri, token, ws_id, cid: deleted.update(id=cid),
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider, ["remove", "-w", "ws-a", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert deleted == {"id": 6}


def test_remove_confirm_abort(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(
        _client,
        "delete_agent_provider",
        lambda *a, **k: pytest.fail("should not delete on abort"),
    )

    result = CliRunner().invoke(
        _agent_providers.agent_provider,
        ["remove", "-w", "ws-a", "--id", "5"],
        input="n\n",
    )
    assert result.exit_code != 0
