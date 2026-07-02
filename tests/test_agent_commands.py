"""Tests for the ``skore agent`` command and ``.skore`` persistence."""

from __future__ import annotations

import json
import re

from click.testing import CliRunner

from skore_cli.agent import _client, _commands, _harnesses
from skore_cli.agent._commands import agent
from skore_cli.agent._harnesses import DEFAULT_MODEL_ID, HARNESSES, HarnessContext
from skore_cli.agent._skore_file import (
    SKORE_FILENAME,
    SkoreConfig,
    ensure_gitignore_entry,
)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _plain_output(output: str) -> str:
    """Strip ANSI codes from rich-click panels for stable assertions."""
    return _ANSI_ESCAPE.sub("", output)


def _mock_harness_on_path(monkeypatch, name: str) -> None:
    """Pretend the harness binary is installed without relying on the real PATH."""
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd == name else None,
    )


def _membership(public_id: str = "ws-1", workspace_id: int = 1):
    return _client.Membership(
        workspace_id=workspace_id,
        public_id=public_id,
        permissions=frozenset(_commands.PROJECT_PERMISSIONS),
    )


def _write_skore(directory, **overrides):
    payload = {
        "hub_url": "http://hub.test",
        "workspace": "ws-1",
        "workspace_id": 1,
        "api_key": "secret-key",
        "harness": "opencode",
    }
    payload.update(overrides)
    (directory / SKORE_FILENAME).write_text(json.dumps(payload) + "\n")
    return payload


def test_skore_config_round_trip(tmp_path):
    config = SkoreConfig(
        hub_url="http://hub.test",
        workspace="ws-1",
        workspace_id=1,
        api_key="secret",
        harness="pi",
    )
    path = config.save(tmp_path)
    loaded = SkoreConfig.load(tmp_path)
    assert path.name == SKORE_FILENAME
    assert loaded == config


def test_skore_config_load_invalid_returns_none(tmp_path):
    (tmp_path / SKORE_FILENAME).write_text("{ not json")
    assert SkoreConfig.load(tmp_path) is None


def test_skore_config_load_normalizes_legacy_claude_code_harness(tmp_path):
    _write_skore(tmp_path, harness="claude-code")
    loaded = SkoreConfig.load(tmp_path)
    assert loaded is not None
    assert loaded.harness == "claude"


def test_ensure_gitignore_appends_entry(tmp_path):
    ensure_gitignore_entry(tmp_path)
    assert (tmp_path / ".gitignore").read_text().strip() == ".skore"

    ensure_gitignore_entry(tmp_path)
    assert (tmp_path / ".gitignore").read_text().count(".skore") == 1


def test_opencode_writer_embeds_api_key(tmp_path):
    HARNESSES["opencode"].configure(
        HarnessContext(
            workspace=tmp_path,
            hub_url="http://hub.test",
            api_key="secret-key",
        )
    )
    config = json.loads((tmp_path / "opencode.json").read_text())
    provider = config["provider"]["skore"]
    assert config["model"] == "skore/skore-agent"
    assert provider["options"]["baseURL"] == "http://hub.test/v1"
    assert provider["options"]["apiKey"] == "secret-key"


def test_agent_nonexistent_workspace_errors(tmp_path):
    missing = tmp_path / "missing"
    result = CliRunner().invoke(agent, ["--workspace", str(missing)])
    assert result.exit_code != 0
    assert "workspace does not exist" in result.output


def test_agent_uses_existing_skore_config(tmp_path, monkeypatch):
    _write_skore(tmp_path)
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: url or "http://hub.test"
    )
    launched: list[str] = []
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda name, workspace, model_id=DEFAULT_MODEL_ID: launched.append(name),
    )

    result = CliRunner().invoke(
        agent,
        ["--workspace", str(tmp_path), "--harness", "opencode"],
    )

    assert result.exit_code == 0, result.output
    assert launched == ["opencode"]
    assert json.loads((tmp_path / "opencode.json").read_text())["provider"]["skore"]


def test_agent_creates_skore_on_first_run(tmp_path, monkeypatch):
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: "http://hub.test"
    )
    monkeypatch.setattr(_commands, "_ensure_login", lambda hub_url, timeout: "tok")
    monkeypatch.setattr(
        _commands._client,
        "me",
        lambda hub_url, token: ("user-1", [_membership()]),
    )
    monkeypatch.setattr(
        _commands._client,
        "list_api_keys",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        _commands._client,
        "create_api_key",
        lambda *a, **k: (42, "new-secret"),
    )
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda name, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(
        agent,
        ["--workspace", str(tmp_path), "--harness", "opencode"],
    )

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["api_key"] == "new-secret"
    assert saved["workspace"] == "ws-1"
    assert (tmp_path / ".gitignore").read_text().strip().endswith(".skore")


def test_agent_non_interactive_without_harness_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: "http://hub.test"
    )
    monkeypatch.setattr(_commands, "_ensure_login", lambda hub_url, timeout: "tok")
    monkeypatch.setattr(
        _commands._client,
        "me",
        lambda hub_url, token: ("user-1", [_membership()]),
    )
    monkeypatch.setattr(_commands, "_is_interactive", lambda: False)

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code != 0
    assert "pass --harness" in _plain_output(result.output)


def test_resolve_api_key_name_deduplicates():
    assert _commands._resolve_api_key_name("opencode", []) == "opencode"
    assert _commands._resolve_api_key_name("opencode", ["opencode"]) == "opencode-2"
    assert (
        _commands._resolve_api_key_name("opencode", ["opencode", "opencode-2"])
        == "opencode-3"
    )
