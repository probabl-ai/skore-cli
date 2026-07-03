"""Tests for the thin hub HTTP client backing ``skore agent``."""

from __future__ import annotations

import httpx
import pytest
import rich_click as click

from skore_cli.agent import _client
from skore_cli.agent._client import ApiKeyInfo, Membership


def _transport(handler):
    """Wrap a request handler in an ``httpx.MockTransport``."""
    return httpx.MockTransport(handler)


# --------------------------------------------------------------------------- #
# me
# --------------------------------------------------------------------------- #


def test_me_parses_user_and_memberships():
    def handler(request):
        assert request.url.path == "/identity/users/me"
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(
            200,
            json={
                "id": "user-1",
                "workspace_memberships": [
                    {
                        "workspace_id": "7",
                        "public_id": "ws-1",
                        "permissions": ["read:project", "create:project"],
                    }
                ],
            },
        )

    user_id, memberships = _client.me(
        "http://hub.test/", "tok", transport=_transport(handler)
    )

    assert user_id == "user-1"
    assert memberships == [
        Membership(
            workspace_id=7,
            public_id="ws-1",
            permissions=frozenset({"read:project", "create:project"}),
        )
    ]


def test_me_handles_missing_memberships():
    def handler(request):
        return httpx.Response(200, json={"id": "user-1"})

    user_id, memberships = _client.me(
        "http://hub.test", "tok", transport=_transport(handler)
    )

    assert user_id == "user-1"
    assert memberships == []


def test_me_membership_without_permissions_is_empty_frozenset():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": "user-1",
                "workspace_memberships": [
                    {"workspace_id": 3, "public_id": "ws-x", "permissions": None}
                ],
            },
        )

    _, memberships = _client.me("http://hub.test", "tok", transport=_transport(handler))

    assert memberships[0].permissions == frozenset()


# --------------------------------------------------------------------------- #
# create_api_key
# --------------------------------------------------------------------------- #


def test_create_api_key_returns_id_and_secret():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/identity/users/user-1/api-keys"
        import json

        body = json.loads(request.content)
        assert body == {
            "name": "opencode",
            "permissions": ["read:project"],
            "workspace_id": 7,
        }
        return httpx.Response(200, json={"api_key_id": 42, "api_key": "secret"})

    key_id, secret = _client.create_api_key(
        "http://hub.test",
        "tok",
        "user-1",
        name="opencode",
        permissions=["read:project"],
        workspace_id=7,
        expires_at=None,
        transport=_transport(handler),
    )

    assert key_id == 42
    assert secret == "secret"


def test_create_api_key_includes_expires_at_when_given():
    def handler(request):
        import json

        body = json.loads(request.content)
        assert body["expires_at"] == "2030-01-01T00:00:00Z"
        return httpx.Response(200, json={"api_key_id": 1, "api_key": "s"})

    _client.create_api_key(
        "http://hub.test",
        "tok",
        "user-1",
        name=None,
        permissions=["read:project"],
        workspace_id=7,
        expires_at="2030-01-01T00:00:00Z",
        transport=_transport(handler),
    )


# --------------------------------------------------------------------------- #
# list_api_keys
# --------------------------------------------------------------------------- #


def test_list_api_keys_parses_metadata():
    def handler(request):
        assert request.url.path == "/identity/users/user-1/api-keys"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "opencode",
                    "workspace_id": "7",
                    "created_at": "2024-01-01",
                    "expires_at": None,
                },
                {"id": 2, "workspace_id": 8},
            ],
        )

    keys = _client.list_api_keys(
        "http://hub.test", "tok", "user-1", transport=_transport(handler)
    )

    assert keys == [
        ApiKeyInfo(
            id=1,
            name="opencode",
            workspace_id=7,
            created_at="2024-01-01",
            expires_at=None,
        ),
        ApiKeyInfo(
            id=2, name=None, workspace_id=8, created_at=None, expires_at=None
        ),
    ]


# --------------------------------------------------------------------------- #
# _raise_for error mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "authentication failed"),
        (403, "not allowed"),
        (404, "not found"),
        (500, "hub request failed"),
    ],
)
def test_error_status_codes_map_to_click_exceptions(status, expected):
    def handler(request):
        return httpx.Response(status, json={"detail": "boom"})

    with pytest.raises(click.ClickException) as excinfo:
        _client.me("http://hub.test", "tok", transport=_transport(handler))

    assert expected in str(excinfo.value)


def test_error_falls_back_to_text_when_body_not_json():
    def handler(request):
        return httpx.Response(500, text="plain text failure")

    with pytest.raises(click.ClickException) as excinfo:
        _client.me("http://hub.test", "tok", transport=_transport(handler))

    assert "plain text failure" in str(excinfo.value)


def test_error_uses_no_details_when_body_empty():
    def handler(request):
        return httpx.Response(500, text="")

    with pytest.raises(click.ClickException) as excinfo:
        _client.list_api_keys(
            "http://hub.test", "tok", "user-1", transport=_transport(handler)
        )

    assert "no details" in str(excinfo.value)
