"""Integration tests: real harness binaries on PATH, config files only."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from skore_cli._agents import (
    CURSOR_ALLOWLIST_ENTRY,
    CURSOR_AUTORUN_INSTRUCTIONS,
    HARNESS_NAMES,
    OPENCODE_SCHEMA,
    get_harness,
    installed_harnesses,
    is_harness_installed,
)
from skore_cli.agent import _client, _commands
from skore_cli.agent._commands import agent
from skore_cli.agent._skore_file import SKORE_FILENAME

pytestmark = pytest.mark.integration

HUB_URL = "http://hub.test"
API_KEY = "secret-key"
MODEL_ID = "skore-agent"
WORKSPACE_PUBLIC_ID = "ws-1"
WORKSPACE_ID = 1

_REQUIRE_ALL = os.environ.get("SKORE_INTEGRATION") == "1"

_CASES = [
    ("opencode", "opencode"),
    ("claude", "claude"),
    ("pi", "pi"),
    ("cursor", "cursor"),
    ("bob", "bob"),
    ("bob-ide", "bob-ide"),
    ("bob-ide", "bobide"),
    ("copilot", "copilot"),
    ("codex", "codex"),
]


def _gitignore_lines(workspace: Path) -> list[str]:
    return (workspace / ".gitignore").read_text().splitlines()


def _assert_skore(workspace: Path, harness: str) -> None:
    saved = json.loads((workspace / ".skore").read_text())
    assert saved["hub_url"] == HUB_URL
    assert saved["workspace"] == WORKSPACE_PUBLIC_ID
    assert saved["workspace_id"] == WORKSPACE_ID
    assert saved["api_key"] == API_KEY
    assert saved["harness"] == harness
    assert ".skore" in _gitignore_lines(workspace)


def _assert_opencode(workspace: Path) -> None:
    config = json.loads((workspace / "opencode.json").read_text())
    assert config["$schema"] == OPENCODE_SCHEMA
    assert config["model"] == f"skore/{MODEL_ID}"
    provider = config["provider"]["skore"]
    assert provider["options"]["baseURL"] == f"{HUB_URL}/v1"
    assert provider["options"]["apiKey"] == API_KEY
    plugin = workspace / ".opencode" / "plugins" / "skore-session.js"
    assert "X-Skore-Session-Id" in plugin.read_text()
    ignored = _gitignore_lines(workspace)
    assert "opencode.json" in ignored
    assert ".opencode/plugins/skore-session.js" in ignored


def _assert_claude(workspace: Path) -> None:
    config = json.loads((workspace / ".claude" / "settings.local.json").read_text())
    assert config["env"] == {
        "ANTHROPIC_BASE_URL": HUB_URL,
        "ANTHROPIC_AUTH_TOKEN": API_KEY,
        "ANTHROPIC_MODEL": MODEL_ID,
    }
    assert ".claude/settings.local.json" in _gitignore_lines(workspace)


def _assert_pi(workspace: Path) -> None:
    config = json.loads((workspace / ".pi" / "agent" / "models.json").read_text())
    provider = config["providers"]["skore"]
    assert provider["baseUrl"] == f"{HUB_URL}/v1"
    assert provider["apiKey"] == API_KEY
    assert provider["models"][0]["id"] == MODEL_ID
    assert ".pi/agent/models.json" in _gitignore_lines(workspace)


def _assert_cursor(workspace: Path) -> None:
    config = json.loads((workspace / ".cursor" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"] == {
        "type": "http",
        "url": f"{HUB_URL}/mcp",
        "headers": {"Authorization": f"Bearer {API_KEY}"},
    }
    permissions = json.loads((workspace / ".cursor" / "permissions.json").read_text())
    assert permissions["mcpAllowlist"] == [CURSOR_ALLOWLIST_ENTRY]
    assert permissions["autoRun"]["allow_instructions"] == list(
        CURSOR_AUTORUN_INSTRUCTIONS
    )
    ignored = _gitignore_lines(workspace)
    assert ".cursor/mcp.json" in ignored
    assert "permissions.json" not in "\n".join(ignored)


def _assert_bob_shell(workspace: Path) -> None:
    config = json.loads((workspace / ".bob" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"] == {
        "httpURL": f"{HUB_URL}/mcp",
        "headers": {"Authorization": f"Bearer {API_KEY}"},
        "alwaysAllow": ["skore_agent"],
        "disabled": False,
    }
    assert ".bob/mcp.json" in _gitignore_lines(workspace)


def _assert_bob_ide(workspace: Path) -> None:
    config = json.loads((workspace / ".bob" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"] == {
        "type": "streamable-http",
        "url": f"{HUB_URL}/mcp",
        "headers": {"Authorization": f"Bearer {API_KEY}"},
        "alwaysAllow": ["skore_agent"],
        "disabled": False,
    }
    assert ".bob/mcp.json" in _gitignore_lines(workspace)


def _assert_copilot(workspace: Path) -> None:
    providers = json.loads(
        (workspace / ".vscode" / "chatLanguageModels.json").read_text()
    )
    skore = next(entry for entry in providers if entry["name"] == "Skore Agent")
    model = skore["models"][0]
    assert model["id"] == MODEL_ID
    assert model["url"] == f"{HUB_URL}/v1/chat/completions"
    assert model["requestHeaders"] == {"X-API-Key": API_KEY}
    assert ".vscode/chatLanguageModels.json" in _gitignore_lines(workspace)


def _assert_codex(workspace: Path) -> None:
    project = tomllib.loads((workspace / ".codex" / "skore-provider.toml").read_text())
    assert project["model"] == MODEL_ID
    assert project["model_provider"] == "skore"
    assert project["base_url"] == f"{HUB_URL}/v1"
    assert project["api_key"] == API_KEY
    assert ".codex/skore-provider.toml" in _gitignore_lines(workspace)


_ASSERTIONS = {
    "opencode": _assert_opencode,
    "claude": _assert_claude,
    "pi": _assert_pi,
    "cursor": _assert_cursor,
    "bob": _assert_bob_shell,
    "bob-ide": _assert_bob_ide,
    "copilot": _assert_copilot,
    "codex": _assert_codex,
}


def _write_skore(directory) -> None:
    payload = {
        "hub_url": HUB_URL,
        "workspace": WORKSPACE_PUBLIC_ID,
        "workspace_id": WORKSPACE_ID,
        "api_key": API_KEY,
        "harness": "opencode",
    }
    (directory / SKORE_FILENAME).write_text(json.dumps(payload, indent=2) + "\n")
    (directory / ".gitignore").write_text(".skore\n")


@pytest.fixture(scope="session", autouse=True)
def require_all_harnesses_in_ci():
    """Fail CI when a vendor harness is missing instead of skipping."""
    if not _REQUIRE_ALL:
        return
    installed = {
        row.harness_name
        for row in installed_harnesses()
        if row.harness_name is not None
    }
    missing = [name for name in HARNESS_NAMES if name not in installed]
    if missing:
        pytest.fail(
            "SKORE_INTEGRATION=1 requires every harness to be installed; "
            f"missing: {', '.join(missing)}"
        )


@pytest.fixture(autouse=True)
def no_hub_http(monkeypatch):
    """Config writers must not contact the hub."""

    def _boom(*args, **kwargs):
        raise AssertionError("hub HTTP must not be used during integration tests")

    monkeypatch.setattr(httpx, "Client", _boom)
    monkeypatch.setattr(_commands, "_ensure_login", _boom)
    monkeypatch.setattr(_client, "me", _boom)
    monkeypatch.setattr(_client, "list_api_keys", _boom)
    monkeypatch.setattr(_client, "create_api_key", _boom)


@pytest.mark.parametrize(("canonical", "harness_flag"), _CASES)
def test_agent_writes_harness_config_without_hub(tmp_path, canonical, harness_flag):
    if not _REQUIRE_ALL and not is_harness_installed(get_harness(canonical)):
        pytest.skip(f"{canonical} is not installed")

    _write_skore(tmp_path)

    result = CliRunner().invoke(
        agent,
        [
            "--workspace",
            str(tmp_path),
            "--harness",
            harness_flag,
            "--no-launch",
        ],
    )

    assert result.exit_code == 0, result.output or repr(result.exception)
    _assert_skore(tmp_path, canonical)
    _ASSERTIONS[canonical](tmp_path)
