"""Thin HTTP client for the hub API used by the ``skore agent`` command.

Pure, testable functions over the hub's ``/identity`` endpoints, limited to what
``skore agent`` needs: reading the user's profile and minting a workspace-scoped
API key. ``httpx`` is imported lazily inside the calls so building the CLI stays
cheap. All calls authenticate with the stored interactive login token as a
bearer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import rich_click as click

_TIMEOUT = 30


@dataclass(frozen=True)
class Membership:
    """A workspace the user belongs to, with the permissions grantable there."""

    workspace_id: int
    public_id: str
    permissions: frozenset[str]


@dataclass(frozen=True)
class ApiKeyInfo:
    """Metadata for an existing API key (the secret is never returned here)."""

    id: int
    name: str | None
    workspace_id: int
    created_at: str | None
    expires_at: str | None


def _client(hub_url: str, token: str, transport: Any = None):
    import httpx

    return httpx.Client(
        base_url=hub_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
        follow_redirects=True,
        transport=transport,
    )


def is_http_url(hub_url: str) -> bool:
    """Return whether ``hub_url`` is an absolute http(s) URL."""
    parsed = urlparse(hub_url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def probe_hub(hub_url: str, *, transport: Any = None) -> bool:
    """Return whether ``hub_url`` looks like a reachable OpenAI-compatible hub."""
    if not hub_url or not is_http_url(hub_url):
        return False
    import httpx

    try:
        with httpx.Client(
            base_url=hub_url.rstrip("/"),
            timeout=_TIMEOUT,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get("/v1/models")
    except httpx.HTTPError:
        return False
    return response.status_code != 404


def _raise_for(response: Any, *, context: str) -> None:
    if response.is_success:
        return
    code = response.status_code
    try:
        detail = response.json().get("detail")
    except Exception:  # noqa: BLE001 - non-JSON error body
        detail = None
    detail = detail or (response.text or "").strip() or "no details"
    if code == 401:
        raise click.ClickException(
            f"authentication failed while {context}; run `skore agent` again."
        )
    if code == 403:
        raise click.ClickException(f"not allowed while {context} ({detail}).")
    if code == 404:
        raise click.ClickException(f"not found while {context} ({detail}).")
    raise click.ClickException(
        f"hub request failed while {context} ({code}: {detail})."
    )


def me(
    hub_url: str, token: str, *, transport: Any = None
) -> tuple[str, list[Membership]]:
    """Return ``(user_id, memberships)`` from ``GET /identity/users/me``."""
    with _client(hub_url, token, transport) as client:
        response = client.get("/identity/users/me")
    _raise_for(response, context="fetching your profile")
    data = response.json()
    memberships = [
        Membership(
            workspace_id=int(item["workspace_id"]),
            public_id=item["public_id"],
            permissions=frozenset(item.get("permissions") or []),
        )
        for item in data.get("workspace_memberships") or []
    ]
    return data["id"], memberships


def create_api_key(
    hub_url: str,
    token: str,
    user_id: str,
    *,
    name: str | None,
    permissions: list[str],
    workspace_id: int,
    expires_at: str | None,
    transport: Any = None,
) -> tuple[int, str]:
    """Create a workspace-scoped API key; return ``(api_key_id, secret)``.

    The plaintext secret is returned only here, once, by the hub.
    """
    body: dict[str, Any] = {
        "name": name,
        "permissions": list(permissions),
        "workspace_id": workspace_id,
    }
    if expires_at is not None:
        body["expires_at"] = expires_at
    with _client(hub_url, token, transport) as client:
        response = client.post(f"/identity/users/{user_id}/api-keys", json=body)
    _raise_for(response, context="creating the API key")
    data = response.json()
    return data["api_key_id"], data["api_key"]


def list_api_keys(
    hub_url: str, token: str, user_id: str, *, transport: Any = None
) -> list[ApiKeyInfo]:
    """Return the user's API keys (metadata only) from the hub."""
    with _client(hub_url, token, transport) as client:
        response = client.get(f"/identity/users/{user_id}/api-keys")
    _raise_for(response, context="listing your API keys")
    return [
        ApiKeyInfo(
            id=item["id"],
            name=item.get("name"),
            workspace_id=int(item["workspace_id"]),
            created_at=item.get("created_at"),
            expires_at=item.get("expires_at"),
        )
        for item in response.json()
    ]
