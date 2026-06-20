"""Tests for ``skore hub workspace`` (client + list/show/create/rename/delete).

The client functions are exercised against an in-memory ``httpx.MockTransport``
(no network). The command callbacks are exercised via ``CliRunner`` with the
``_client`` functions and the session helpers monkeypatched, plus a fake
``IdPicker`` for the interactive selection path (mirroring the api-key and
agent-provider tests).
"""

from __future__ import annotations

import json

import httpx
import pytest
import rich_click as click
from click.testing import CliRunner

from skore_cli.hub import _api_keys, _client, _workspaces
from skore_cli.hub._client import MemberInfo, Membership, WorkspaceInfo


def _transport(handler):
    return httpx.MockTransport(handler)


def _ws(**overrides):
    base = {
        "id": 7,
        "public_id": "ws-a",
        "is_public": False,
        "created_at": "2026-01-01T00:00:00Z",
        "members": [{"user_id": "user-1", "role": "owner", "invited_by": None}],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# _client: HTTP calls via MockTransport
# --------------------------------------------------------------------------- #


def test_list_workspaces_parses_and_paginates():
    seen = {"calls": 0}

    def handler(request):
        assert request.url.path == "/identity/workspaces"
        assert request.headers["Authorization"] == "Bearer tok"
        seen["calls"] += 1
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(
                200, json={"items": [_ws(id=7, public_id="ws-a")], "next_cursor": 5}
            )
        assert cursor == "5"
        return httpx.Response(
            200, json={"items": [_ws(id=8, public_id="ws-b")], "next_cursor": None}
        )

    result = _client.list_workspaces(
        "http://hub.test", "tok", transport=_transport(handler)
    )
    assert seen["calls"] == 2
    assert [w.id for w in result] == [7, 8]
    assert result[0].members == [MemberInfo("user-1", "owner", None)]


def test_get_workspace_parses_members():
    def handler(request):
        assert request.url.path == "/identity/workspaces/7"
        return httpx.Response(
            200,
            json=_ws(
                members=[
                    {"user_id": "user-1", "role": "owner", "invited_by": None},
                    {"user_id": "user-2", "role": "reader", "invited_by": "user-1"},
                ]
            ),
        )

    ws = _client.get_workspace(
        "http://hub.test", "tok", 7, transport=_transport(handler)
    )
    assert ws.id == 7
    assert ws.members == [
        MemberInfo("user-1", "owner", None),
        MemberInfo("user-2", "reader", "user-1"),
    ]


def test_create_workspace_posts_body_and_returns_id():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 42})

    workspace_id = _client.create_workspace(
        "http://hub.test", "tok", public_id="my-ws", transport=_transport(handler)
    )
    assert workspace_id == 42
    assert seen["path"] == "/identity/workspaces"
    assert seen["body"] == {"public_id": "my-ws"}


def test_check_public_id_parses():
    def handler(request):
        assert request.url.path == "/identity/workspaces/public-id-availability"
        assert request.url.params.get("public_id") == "my-ws"
        return httpx.Response(
            200, json={"available": False, "suggested_slug": "my-ws-1"}
        )

    available, suggested = _client.check_public_id(
        "http://hub.test", "tok", "my-ws", transport=_transport(handler)
    )
    assert (available, suggested) == (False, "my-ws-1")


def test_update_workspace_puts_body():
    seen = {}

    def handler(request):
        assert request.method == "PUT"
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(204)

    _client.update_workspace(
        "http://hub.test", "tok", 7, public_id="new-ws", transport=_transport(handler)
    )
    assert seen["path"] == "/identity/workspaces/7"
    assert seen["body"] == {"public_id": "new-ws"}


def test_delete_workspace_hits_path():
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.path == "/identity/workspaces/7"
        return httpx.Response(204)

    _client.delete_workspace("http://hub.test", "tok", 7, transport=_transport(handler))


def test_delete_403_maps_owner_only():
    def handler(request):
        return httpx.Response(403, json={"detail": "forbidden"})

    with pytest.raises(click.ClickException) as exc:
        _client.delete_workspace(
            "http://hub.test", "tok", 7, transport=_transport(handler)
        )
    assert "owner only" in str(exc.value)


def test_get_404_maps_not_found():
    def handler(request):
        return httpx.Response(404, json={"detail": "nope"})

    with pytest.raises(click.ClickException) as exc:
        _client.get_workspace(
            "http://hub.test", "tok", 7, transport=_transport(handler)
        )
    assert "not found" in str(exc.value)


# --------------------------------------------------------------------------- #
# helpers for command tests
# --------------------------------------------------------------------------- #


def _patch_session(monkeypatch, memberships, *, user_id="user-1"):
    monkeypatch.setattr(_api_keys, "resolve_hub_uri", lambda url, *a, **k: url or "h")
    monkeypatch.setattr(_client, "require_login_token", lambda: "tok")
    monkeypatch.setattr(_client, "me", lambda uri, token: (user_id, memberships))


_WS_A = Membership(7, "ws-a", frozenset())
_WS_B = Membership(8, "ws-b", frozenset())


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_list_requires_login(monkeypatch):
    monkeypatch.setattr(_api_keys, "resolve_hub_uri", lambda url, *a, **k: "h")

    def boom():
        raise click.ClickException("not logged in; run `skore hub login` first.")

    monkeypatch.setattr(_client, "require_login_token", boom)

    result = CliRunner().invoke(_workspaces.workspace, ["list"])
    assert result.exit_code != 0
    assert "not logged in" in result.output


def test_list_prints_table(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(
        _client,
        "list_workspaces",
        lambda uri, token: [
            WorkspaceInfo(
                7,
                "ws-a",
                False,
                "2026-01-01T00:00:00Z",
                [MemberInfo("user-1", "owner", None)],
            )
        ],
    )

    result = CliRunner().invoke(
        _workspaces.workspace, ["list", "--hub-url", "http://h"]
    )
    assert result.exit_code == 0, result.output
    assert "ws-a" in result.output
    assert "owner" in result.output


def test_list_empty(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_client, "list_workspaces", lambda uri, token: [])

    result = CliRunner().invoke(_workspaces.workspace, ["list"])
    assert result.exit_code == 0, result.output
    assert "No workspaces" in result.output


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #


def test_show_prints_members(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)
    monkeypatch.setattr(
        _client,
        "get_workspace",
        lambda uri, token, ws_id: WorkspaceInfo(
            7,
            "ws-a",
            False,
            "2026-01-01T00:00:00Z",
            [MemberInfo("user-1", "owner", None)],
        ),
    )

    result = CliRunner().invoke(_workspaces.workspace, ["show", "-w", "ws-a"])
    assert result.exit_code == 0, result.output
    assert "ws-a" in result.output
    assert "user-1" in result.output
    assert "owner" in result.output


def test_show_unknown_workspace_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)

    result = CliRunner().invoke(_workspaces.workspace, ["show", "-w", "nope"])
    assert result.exit_code != 0
    assert "unknown workspace" in result.output


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #


def test_create_with_public_id(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)
    monkeypatch.setattr(
        _client, "check_public_id", lambda uri, token, pid: (True, None)
    )
    captured = {}

    def fake_create(uri, token, *, public_id):
        captured["public_id"] = public_id
        return 42

    monkeypatch.setattr(_client, "create_workspace", fake_create)
    monkeypatch.setattr(
        _client,
        "get_workspace",
        lambda uri, token, ws_id: WorkspaceInfo(42, "my-ws", False, None, None),
    )

    result = CliRunner().invoke(
        _workspaces.workspace, ["create", "--public-id", "my-ws"]
    )
    assert result.exit_code == 0, result.output
    assert captured["public_id"] == "my-ws"
    assert "created workspace" in result.output
    assert "my-ws" in result.output


def test_create_taken_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)
    monkeypatch.setattr(
        _client, "check_public_id", lambda uri, token, pid: (False, "my-ws-1")
    )
    monkeypatch.setattr(
        _client,
        "create_workspace",
        lambda *a, **k: pytest.fail("should not create when taken"),
    )

    result = CliRunner().invoke(
        _workspaces.workspace, ["create", "--public-id", "my-ws"]
    )
    assert result.exit_code != 0
    assert "not available" in result.output
    assert "my-ws-1" in result.output


def test_create_interactive_prompt(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        _client, "check_public_id", lambda uri, token, pid: (True, None)
    )
    captured = {}

    def fake_create(uri, token, *, public_id):
        captured["public_id"] = public_id
        return 42

    monkeypatch.setattr(_client, "create_workspace", fake_create)
    monkeypatch.setattr(
        _client,
        "get_workspace",
        lambda uri, token, ws_id: WorkspaceInfo(42, "prompted", False, None, None),
    )

    result = CliRunner().invoke(_workspaces.workspace, ["create"], input="prompted\n")
    assert result.exit_code == 0, result.output
    assert captured["public_id"] == "prompted"


def test_create_non_interactive_missing_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)

    result = CliRunner().invoke(_workspaces.workspace, ["create"])
    assert result.exit_code != 0
    assert "--public-id" in result.output


# --------------------------------------------------------------------------- #
# rename
# --------------------------------------------------------------------------- #


def test_rename_with_flags(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)
    captured = {}

    def fake_update(uri, token, ws_id, *, public_id):
        captured.update(ws_id=ws_id, public_id=public_id)

    monkeypatch.setattr(_client, "update_workspace", fake_update)
    monkeypatch.setattr(
        _client,
        "get_workspace",
        lambda uri, token, ws_id: WorkspaceInfo(7, "new-ws", False, None, None),
    )

    result = CliRunner().invoke(
        _workspaces.workspace,
        ["rename", "-w", "ws-a", "--new-public-id", "new-ws"],
    )
    assert result.exit_code == 0, result.output
    assert captured == {"ws_id": 7, "public_id": "new-ws"}
    assert "new-ws" in result.output


def test_rename_non_interactive_missing_new_errors(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)

    result = CliRunner().invoke(_workspaces.workspace, ["rename", "-w", "ws-a"])
    assert result.exit_code != 0
    assert "--new-public-id" in result.output


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #


def test_delete_yes(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)
    deleted = {}
    monkeypatch.setattr(
        _client,
        "delete_workspace",
        lambda uri, token, ws_id: deleted.update(ws_id=ws_id),
    )

    result = CliRunner().invoke(
        _workspaces.workspace, ["delete", "-w", "ws-a", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert deleted == {"ws_id": 7}
    assert "deleted workspace ws-a" in result.output


def test_delete_confirm_abort(monkeypatch):
    _patch_session(monkeypatch, [_WS_A])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: False)
    monkeypatch.setattr(
        _client,
        "delete_workspace",
        lambda *a, **k: pytest.fail("should not delete on abort"),
    )

    result = CliRunner().invoke(
        _workspaces.workspace, ["delete", "-w", "ws-a"], input="n\n"
    )
    assert result.exit_code != 0


def test_delete_interactive_picker(monkeypatch):
    from skore_cli.hub import app as hub_app

    _patch_session(monkeypatch, [_WS_A, _WS_B])
    monkeypatch.setattr(_workspaces, "_is_interactive", lambda: True)

    class _FakePicker:
        def __init__(self, *a, **k):
            self.result = 8

        def run(self):
            return None

    monkeypatch.setattr(hub_app, "IdPicker", _FakePicker)
    deleted = {}
    monkeypatch.setattr(
        _client,
        "delete_workspace",
        lambda uri, token, ws_id: deleted.update(ws_id=ws_id),
    )

    result = CliRunner().invoke(_workspaces.workspace, ["delete", "--yes"])
    assert result.exit_code == 0, result.output
    assert deleted == {"ws_id": 8}
    assert "deleted workspace ws-b" in result.output
