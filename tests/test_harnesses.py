"""Tests for the harness registry, helpers, detection and config writers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from skore_cli.agent import _harnesses
from skore_cli.agent._harnesses import (
    API_KEY_ENV,
    HARNESSES,
    WORKSPACE_HEADER,
    ConfigureContext,
    Credential,
    base_url,
    detect_harnesses,
    fetch_workspaces,
    header_pair,
    resolve_credential,
    workspace_headers,
)


@pytest.fixture
def cap(monkeypatch):
    """Capture raw console markup emitted by the harness module."""
    messages: list[str] = []
    monkeypatch.setattr(
        _harnesses, "console", SimpleNamespace(print=lambda *a, **k: messages.append(
            " ".join(str(x) for x in a)
        ))
    )
    return messages


@pytest.fixture
def no_api_key(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)


def _ctx(workspace, cred, **kwargs):
    return ConfigureContext(
        workspace=workspace,
        hub_url="http://hub.test",
        model_id="skore-agent",
        cred=cred,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_base_url_strips_and_appends_v1():
    assert base_url("http://hub.test/") == "http://hub.test/v1"
    assert base_url("http://hub.test") == "http://hub.test/v1"


def test_header_pair_api_key():
    assert header_pair(Credential("api_key")) == ("X-API-Key", f"{{env:{API_KEY_ENV}}}")


def test_header_pair_bearer():
    assert header_pair(Credential("bearer", "tok")) == ("Authorization", "Bearer tok")


def test_header_pair_none():
    assert header_pair(Credential("none")) is None


def test_workspace_headers_set_and_unset(tmp_path):
    with_ws = _ctx(tmp_path, Credential("bearer", "t"), hub_workspace="ws-1")
    without_ws = _ctx(tmp_path, Credential("bearer", "t"), hub_workspace=None)
    assert workspace_headers(with_ws) == {WORKSPACE_HEADER: "ws-1"}
    assert workspace_headers(without_ws) == {}


# --------------------------------------------------------------------------- #
# resolve_credential
# --------------------------------------------------------------------------- #


def test_resolve_credential_api_key(monkeypatch, no_api_key):
    monkeypatch.setenv(API_KEY_ENV, "uid:secret")
    assert resolve_credential() == Credential("api_key")


def test_resolve_credential_bearer(monkeypatch, no_api_key):
    monkeypatch.setattr(
        _harnesses,
        "_auth",
        lambda name: SimpleNamespace(
            fresh_token=lambda relogin: {"access_token": "tok"}
        ),
    )
    assert resolve_credential() == Credential("bearer", "tok")


def test_resolve_credential_none(monkeypatch, no_api_key):
    monkeypatch.setattr(
        _harnesses,
        "_auth",
        lambda name: SimpleNamespace(fresh_token=lambda relogin: None),
    )
    assert resolve_credential() == Credential("none")


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #


def test_detect_opencode_by_file(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda name: None)
    (tmp_path / "opencode.json").write_text("{}")
    assert _harnesses._detect_opencode(tmp_path) is True


def test_detect_opencode_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda name: "/usr/bin/opencode")
    assert _harnesses._detect_opencode(tmp_path) is True


def test_detect_continue_by_home(workspace):
    assert _harnesses._detect_continue(workspace.project) is False
    (workspace.home / ".continue").mkdir()
    assert _harnesses._detect_continue(workspace.project) is True


def test_detect_harnesses_excludes_generic(tmp_path, monkeypatch, workspace):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda name: None)
    (workspace.project / "opencode.json").write_text("{}")
    detected = detect_harnesses(workspace.project)
    assert "opencode" in detected
    assert "generic" not in detected


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def _opencode_config(workspace):
    return json.loads((workspace / "opencode.json").read_text())


def test_opencode_api_key_uses_env_reference(tmp_path, cap, monkeypatch, no_api_key):
    monkeypatch.setenv(API_KEY_ENV, "uid:secret")
    extra = HARNESSES["opencode"].configure(
        _ctx(tmp_path, Credential("api_key"), write_session_plugin=False)
    )
    headers = _opencode_config(tmp_path)["provider"]["skore"]["options"]["headers"]
    assert headers["X-API-Key"] == f"{{env:{API_KEY_ENV}}}"
    assert extra["session_plugin"] is False


def test_opencode_bearer_writes_session_plugin(tmp_path, cap):
    extra = HARNESSES["opencode"].configure(
        _ctx(
            tmp_path,
            Credential("bearer", "tok"),
            hub_workspace="ws-1",
            write_session_plugin=True,
        )
    )
    assert extra["session_plugin"] is True
    plugin = tmp_path / ".opencode" / "plugin" / "skore-session.js"
    assert plugin.is_file()
    headers = _opencode_config(tmp_path)["provider"]["skore"]["options"]["headers"]
    assert headers["Authorization"] == "Bearer tok"
    assert headers[WORKSPACE_HEADER] == "ws-1"


def test_opencode_backs_up_invalid_json(tmp_path, cap):
    (tmp_path / "opencode.json").write_text("{ not json")
    HARNESSES["opencode"].configure(
        _ctx(tmp_path, Credential("none"), write_session_plugin=False)
    )
    assert (tmp_path / "opencode.json.bak").is_file()
    assert _opencode_config(tmp_path)["provider"]["skore"]["npm"]


def test_copilot_bearer_embeds_token(tmp_path, cap):
    extra = HARNESSES["copilot"].configure(_ctx(tmp_path, Credential("bearer", "tok")))
    content = Path(extra["env_file"]).read_text()
    assert 'COPILOT_PROVIDER_API_KEY="tok"' in content
    assert 'COPILOT_PROVIDER_BASE_URL="http://hub.test/v1"' in content


def test_copilot_api_key_references_env(tmp_path, cap, monkeypatch, no_api_key):
    monkeypatch.setenv(API_KEY_ENV, "uid:secret")
    extra = HARNESSES["copilot"].configure(_ctx(tmp_path, Credential("api_key")))
    content = Path(extra["env_file"]).read_text()
    assert f'COPILOT_PROVIDER_API_KEY="${API_KEY_ENV}"' in content


def test_cline_writes_settings(tmp_path, cap):
    extra = HARNESSES["cline"].configure(_ctx(tmp_path, Credential("api_key")))
    settings = json.loads(Path(extra["settings_path"]).read_text())
    assert settings["cline.apiProvider"] == "openai-compatible"
    assert settings["cline.openAiBaseUrl"] == "http://hub.test/v1"
    assert settings["cline.apiModelId"] == "skore-agent"


def test_cline_backs_up_invalid_json(tmp_path, cap):
    settings_dir = tmp_path / ".vscode"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text("{ bad")
    HARNESSES["cline"].configure(_ctx(tmp_path, Credential("none")))
    assert (settings_dir / "settings.json.bak").is_file()


def test_generic_writes_file_with_headers(tmp_path, cap):
    extra = HARNESSES["generic"].configure(
        _ctx(tmp_path, Credential("bearer", "tok"), hub_workspace="ws-1")
    )
    payload = json.loads(Path(extra["config_file"]).read_text())
    assert payload["baseURL"] == "http://hub.test/v1"
    assert payload["headers"]["Authorization"] == "Bearer tok"
    assert payload["headers"][WORKSPACE_HEADER] == "ws-1"


def test_generic_no_file_when_disabled(tmp_path, cap):
    extra = HARNESSES["generic"].configure(
        _ctx(tmp_path, Credential("api_key"), write_file=False)
    )
    assert "config_file" not in extra
    assert not (tmp_path / "skore-agent.json").exists()


def test_generic_none_credential_note(tmp_path, cap):
    HARNESSES["generic"].configure(_ctx(tmp_path, Credential("none"), write_file=False))
    assert any("no credential resolved" in m for m in cap)


def test_continue_merges_model_block(workspace, cap):
    extra = HARNESSES["continue"].configure(
        _ctx(workspace.project, Credential("bearer", "tok"), hub_workspace="ws-1")
    )
    import yaml

    config = yaml.safe_load(Path(extra["config_path"]).read_text())
    blocks = [m for m in config["models"] if m["name"] == "Skore Hub Agent"]
    assert len(blocks) == 1
    assert blocks[0]["apiBase"] == "http://hub.test/v1"
    headers = blocks[0]["requestOptions"]["headers"]
    assert headers["Authorization"] == "Bearer tok"
    assert headers[WORKSPACE_HEADER] == "ws-1"


def test_continue_backs_up_existing(workspace, cap):
    config_dir = workspace.home / ".continue"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("name: Existing\nmodels: []\n")
    HARNESSES["continue"].configure(_ctx(workspace.project, Credential("api_key")))
    assert (config_dir / "config.yaml.bak").is_file()


def test_claude_code_writes_proxy_and_env(workspace, cap):
    extra = HARNESSES["claude-code"].configure(
        _ctx(workspace.project, Credential("bearer", "tok"))
    )
    import yaml

    proxy = yaml.safe_load(Path(extra["proxy_config"]).read_text())
    entry = proxy["model_list"][0]
    assert entry["model_name"] == "skore-agent"
    assert entry["litellm_params"]["api_base"] == "http://hub.test/v1"
    env_text = Path(extra["env_file"]).read_text()
    assert "ANTHROPIC_BASE_URL" in env_text


# --------------------------------------------------------------------------- #
# fetch_workspaces (httpx injected as a fake module)
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_httpx(payload, captured):
    def get(url, headers=None, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse(payload)

    return SimpleNamespace(get=get)


def test_fetch_workspaces_api_key_header(monkeypatch, no_api_key):
    monkeypatch.setenv(API_KEY_ENV, "uid:secret")
    captured: dict = {}
    monkeypatch.setitem(
        sys.modules, "httpx", _fake_httpx({"items": []}, captured)
    )
    fetch_workspaces("http://hub.test", Credential("api_key"))
    assert captured["headers"] == {"X-API-Key": "uid:secret"}
    assert captured["url"] == "http://hub.test/identity/workspaces"


def test_fetch_workspaces_bearer_header(monkeypatch, no_api_key):
    captured: dict = {}
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx([], captured))
    fetch_workspaces("http://hub.test", Credential("bearer", "tok"))
    assert captured["headers"] == {"Authorization": "Bearer tok"}


def test_fetch_workspaces_parses_items_and_fallbacks(monkeypatch, no_api_key):
    payload = {
        "items": [
            {"public_id": "ws-1", "name": "First"},
            {"slug": "ws-2"},
            {"name": "no-id"},
        ]
    }
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(payload, {}))
    result = fetch_workspaces("http://hub.test", Credential("bearer", "tok"))
    assert result == [("ws-1", "First"), ("ws-2", "ws-2")]


def test_fetch_workspaces_accepts_bare_list(monkeypatch, no_api_key):
    payload = [{"public_id": "ws-1", "name": "First"}]
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(payload, {}))
    result = fetch_workspaces("http://hub.test", Credential("bearer", "tok"))
    assert result == [("ws-1", "First")]
