"""Tests for attaching the agent to a hub workspace (`skore agent model install`)."""

from __future__ import annotations

import json

import pytest
import rich_click as click
from click.testing import CliRunner

from skore_cli.agent._harnesses import (
    HARNESSES,
    WORKSPACE_HEADER,
    ConfigureContext,
    Credential,
)
from skore_cli.agent.model import _commands
from skore_cli.agent.model._commands import install


def _opencode_headers(workspace, cred, hub_workspace):
    ctx = ConfigureContext(
        workspace=workspace,
        hub_url="http://hub.test",
        model_id="skore-agent",
        cred=cred,
        hub_workspace=hub_workspace,
        write_session_plugin=False,
    )
    HARNESSES["opencode"].configure(ctx)
    config = json.loads((workspace / "opencode.json").read_text())
    return config["provider"]["skore"]["options"].get("headers", {})


def test_opencode_writes_workspace_header_for_bearer(tmp_path):
    headers = _opencode_headers(
        tmp_path, Credential("bearer", "tok"), hub_workspace="ws-x"
    )
    assert headers[WORKSPACE_HEADER] == "ws-x"
    assert headers["Authorization"] == "Bearer tok"


def test_opencode_no_workspace_header_for_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    # API keys are workspace-bound server-side: no header is written.
    headers = _opencode_headers(tmp_path, Credential("api_key"), hub_workspace=None)
    assert WORKSPACE_HEADER not in headers
    assert headers["X-API-Key"] == "{env:SKORE_HUB_API_KEY}"


def test_install_records_attached_workspace_in_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _commands, "resolve_credential", lambda: Credential("bearer", "tok")
    )
    # Resolve the hub URL without importing the (absent) skore package.
    monkeypatch.setattr(_commands, "resolve_hub_uri", lambda url, *a, **k: url)
    result = CliRunner().invoke(
        install,
        [
            "--workspace",
            str(tmp_path),
            "--harness",
            "opencode",
            "--hub-url",
            "http://hub.test",
            "--hub-workspace",
            "ws-x",
            "--no-session-plugin",
            "--no-skills",
        ],
    )
    assert result.exit_code == 0, result.output
    marker = json.loads((tmp_path / ".skore-agent.json").read_text())
    assert marker["hub_workspace"] == "ws-x"


# --------------------------------------------------------------------------- #
# _resolve_hub_workspace
# --------------------------------------------------------------------------- #


def test_resolve_api_key_ignores_workspace():
    # API key path resolves to no attached slug (bound server-side).
    assert (
        _commands._resolve_hub_workspace(
            Credential("api_key"), "http://hub.test", "ws-x"
        )
        is None
    )


def test_resolve_bearer_uses_flag():
    assert (
        _commands._resolve_hub_workspace(
            Credential("bearer", "tok"), "http://hub.test", "ws-1"
        )
        == "ws-1"
    )


def test_resolve_bearer_non_interactive_without_flag_errors(monkeypatch):
    monkeypatch.setattr(
        _commands, "fetch_workspaces", lambda hub_url, cred: [("ws-1", "ws-1")]
    )
    monkeypatch.setattr(_commands, "_is_interactive", lambda: False)
    with pytest.raises(click.UsageError):
        _commands._resolve_hub_workspace(
            Credential("bearer", "tok"), "http://hub.test", None
        )


def test_resolve_bearer_no_workspaces_errors(monkeypatch):
    monkeypatch.setattr(_commands, "fetch_workspaces", lambda hub_url, cred: [])
    with pytest.raises(click.ClickException):
        _commands._resolve_hub_workspace(
            Credential("bearer", "tok"), "http://hub.test", None
        )


def test_resolve_bearer_interactive_uses_picker(monkeypatch):
    monkeypatch.setattr(
        _commands,
        "fetch_workspaces",
        lambda hub_url, cred: [("ws-1", "ws-1"), ("ws-2", "ws-2")],
    )
    monkeypatch.setattr(_commands, "_is_interactive", lambda: True)
    monkeypatch.setattr(_commands, "_pick_workspace", lambda workspaces: "ws-2")
    assert (
        _commands._resolve_hub_workspace(
            Credential("bearer", "tok"), "http://hub.test", None
        )
        == "ws-2"
    )
