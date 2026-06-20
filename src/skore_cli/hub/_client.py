"""Thin HTTP client for the hub API used by ``skore hub`` management commands.

Pure, testable functions over the hub's ``/identity`` and ``/agent`` endpoints.
``httpx`` is imported lazily inside the calls so building the CLI stays cheap.
All management calls authenticate with the stored interactive login token as a
bearer.

The current user's profile (``GET /identity/users/me``) is the single source of
truth for both the workspaces the user belongs to (``workspace_id`` +
``public_id``) and the permissions grantable in each of them, mirroring how the
hub UI gates the forms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import rich_click as click

from skore_cli._skore import auth as _auth

# The grantable permissions, kept as local literals so ``--help`` never imports
# the (heavy) ``skore``/hub packages. Mirrors hub ``Permission`` enum values.
PERMISSIONS = [
    "create:project",
    "read:project",
    "update:project",
    "delete:project",
    "create:invitation",
    "read:invitation",
    "delete:invitation",
]

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


# The agent provider types the hub supports, kept as local literals.
AGENT_PROVIDERS = ["skore", "anthropic", "bedrock"]


@dataclass(frozen=True)
class ProviderEntry:
    """A workspace's registered agent provider (secrets are masked as ``*_set``)."""

    id: int
    name: str
    is_active: bool
    provider: str
    selected_model: str | None
    aws_region: str | None
    bedrock_role_arn: str | None
    anthropic_api_key_set: bool
    bedrock_external_id_set: bool
    aws_access_key_id_set: bool
    aws_secret_access_key_set: bool


@dataclass(frozen=True)
class AgentProviders:
    """The workspace's providers plus the UI metadata the create form needs."""

    providers: list[ProviderEntry]
    available_models: dict[str, list[str]]
    encryption_configured: bool


@dataclass(frozen=True)
class MemberInfo:
    """A workspace member (no email/name is exposed by the hub, only the id)."""

    user_id: str
    role: str
    invited_by: str | None


@dataclass(frozen=True)
class WorkspaceInfo:
    """A workspace the user can act on, with its members when fetched in detail."""

    id: int
    public_id: str
    is_public: bool
    created_at: str | None
    members: list[MemberInfo] | None


def require_login_token() -> str:
    """Return a fresh OAuth bearer token, or error telling the user to log in.

    This gates ``skore hub api-key`` behind a prior ``skore hub login``: an
    ``SKORE_HUB_API_KEY`` alone is intentionally not sufficient to mint new keys.
    """
    token = _auth("token").fresh_token(relogin=False)
    if not token or not token.get("access_token"):
        raise click.ClickException(
            "not logged in; run `skore hub login` first. API keys are minted with "
            "your interactive login, not an existing SKORE_HUB_API_KEY."
        )
    return token["access_token"]


def _client(hub_url: str, token: str, transport: Any = None):
    import httpx

    return httpx.Client(
        base_url=hub_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
        follow_redirects=True,
        transport=transport,
    )


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
            f"authentication failed while {context}; run `skore hub login` again."
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


def delete_api_key(
    hub_url: str, token: str, user_id: str, api_key_id: int, *, transport: Any = None
) -> None:
    """Revoke an API key by id."""
    with _client(hub_url, token, transport) as client:
        response = client.delete(f"/identity/users/{user_id}/api-keys/{api_key_id}")
    _raise_for(response, context=f"revoking API key {api_key_id}")


def _provider_entry(item: dict[str, Any]) -> ProviderEntry:
    return ProviderEntry(
        id=item["id"],
        name=item["name"],
        is_active=bool(item.get("is_active")),
        provider=item["provider"],
        selected_model=item.get("selected_model"),
        aws_region=item.get("aws_region"),
        bedrock_role_arn=item.get("bedrock_role_arn"),
        anthropic_api_key_set=bool(item.get("anthropic_api_key_set")),
        bedrock_external_id_set=bool(item.get("bedrock_external_id_set")),
        aws_access_key_id_set=bool(item.get("aws_access_key_id_set")),
        aws_secret_access_key_set=bool(item.get("aws_secret_access_key_set")),
    )


def agent_providers(
    hub_url: str, token: str, workspace_id: int, *, transport: Any = None
) -> AgentProviders:
    """Return a workspace's agent providers plus create-form metadata."""
    with _client(hub_url, token, transport) as client:
        response = client.get(f"/agent/workspaces/{workspace_id}/providers")
    _raise_for(response, context="listing agent providers")
    data = response.json()
    return AgentProviders(
        providers=[_provider_entry(item) for item in data.get("providers") or []],
        available_models={
            key: list(value)
            for key, value in (data.get("available_models") or {}).items()
        },
        encryption_configured=bool(data.get("encryption_configured")),
    )


def create_agent_provider(
    hub_url: str,
    token: str,
    workspace_id: int,
    *,
    payload: dict[str, Any],
    transport: Any = None,
) -> ProviderEntry:
    """Register a new agent provider; return the created (masked) entry."""
    with _client(hub_url, token, transport) as client:
        response = client.post(
            f"/agent/workspaces/{workspace_id}/providers", json=payload
        )
    _raise_for(
        response,
        context="adding the provider (needs workspace owner/admin)",
    )
    return _provider_entry(response.json())


def activate_agent_provider(
    hub_url: str,
    token: str,
    workspace_id: int,
    config_id: int,
    *,
    transport: Any = None,
) -> None:
    """Activate one provider for the workspace (deactivates the others)."""
    with _client(hub_url, token, transport) as client:
        response = client.post(
            f"/agent/workspaces/{workspace_id}/providers/{config_id}/activate"
        )
    _raise_for(
        response,
        context=f"activating provider {config_id} (needs workspace owner/admin)",
    )


def delete_agent_provider(
    hub_url: str,
    token: str,
    workspace_id: int,
    config_id: int,
    *,
    transport: Any = None,
) -> None:
    """Remove a provider from the workspace."""
    with _client(hub_url, token, transport) as client:
        response = client.delete(
            f"/agent/workspaces/{workspace_id}/providers/{config_id}"
        )
    _raise_for(
        response,
        context=f"removing provider {config_id} (needs workspace owner/admin)",
    )


def _workspace_info(item: dict[str, Any]) -> WorkspaceInfo:
    members = item.get("members")
    return WorkspaceInfo(
        id=int(item["id"]),
        public_id=item["public_id"],
        is_public=bool(item.get("is_public")),
        created_at=item.get("created_at"),
        members=(
            [
                MemberInfo(
                    user_id=str(member["user_id"]),
                    role=member.get("role") or "",
                    invited_by=member.get("invited_by"),
                )
                for member in members
            ]
            if members is not None
            else None
        ),
    )


def list_workspaces(
    hub_url: str, token: str, *, transport: Any = None
) -> list[WorkspaceInfo]:
    """Return every workspace the user belongs to (following the cursor)."""
    workspaces: list[WorkspaceInfo] = []
    cursor: int | None = None
    with _client(hub_url, token, transport) as client:
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get("/identity/workspaces", params=params)
            _raise_for(response, context="listing your workspaces")
            data = response.json()
            workspaces.extend(_workspace_info(item) for item in data.get("items") or [])
            cursor = data.get("next_cursor")
            if cursor is None:
                break
    return workspaces


def get_workspace(
    hub_url: str, token: str, workspace_id: int, *, transport: Any = None
) -> WorkspaceInfo:
    """Return a single workspace (with its members) by internal id."""
    with _client(hub_url, token, transport) as client:
        response = client.get(f"/identity/workspaces/{workspace_id}")
    _raise_for(response, context="fetching the workspace")
    return _workspace_info(response.json())


def create_workspace(
    hub_url: str, token: str, *, public_id: str, transport: Any = None
) -> int:
    """Create a workspace; return its internal id.

    The hub slugifies ``public_id`` and auto-suffixes it when taken, so the
    stored public id may differ from the requested one (re-fetch to confirm).
    """
    with _client(hub_url, token, transport) as client:
        response = client.post("/identity/workspaces", json={"public_id": public_id})
    _raise_for(response, context="creating the workspace")
    return int(response.json()["id"])


def check_public_id(
    hub_url: str, token: str, public_id: str, *, transport: Any = None
) -> tuple[bool, str | None]:
    """Return ``(available, suggested_slug)`` for a candidate workspace public id."""
    with _client(hub_url, token, transport) as client:
        response = client.get(
            "/identity/workspaces/public-id-availability",
            params={"public_id": public_id},
        )
    _raise_for(response, context="checking workspace availability")
    data = response.json()
    return bool(data.get("available")), data.get("suggested_slug")


def update_workspace(
    hub_url: str,
    token: str,
    workspace_id: int,
    *,
    public_id: str,
    transport: Any = None,
) -> None:
    """Rename a workspace (its ``public_id``); needs workspace owner/admin."""
    with _client(hub_url, token, transport) as client:
        response = client.put(
            f"/identity/workspaces/{workspace_id}", json={"public_id": public_id}
        )
    _raise_for(
        response,
        context="renaming the workspace (needs workspace owner/admin)",
    )


def delete_workspace(
    hub_url: str, token: str, workspace_id: int, *, transport: Any = None
) -> None:
    """Delete a workspace; owner only (hard delete on the hub)."""
    with _client(hub_url, token, transport) as client:
        response = client.delete(f"/identity/workspaces/{workspace_id}")
    _raise_for(
        response,
        context="deleting the workspace (owner only)",
    )
