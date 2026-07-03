"""Tests for the harness registry, detection and config writers."""

from __future__ import annotations

import json

import pytest

from skore_cli.agent import _harnesses
from skore_cli.agent._harnesses import (
    HARNESSES,
    HarnessContext,
    detect_harnesses,
)


def _ctx(workspace, **kwargs):
    return HarnessContext(
        workspace=workspace,
        hub_url="http://hub.test",
        api_key="secret-key",
        **kwargs,
    )


def test_detect_opencode_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )
    assert _harnesses._detect_opencode(tmp_path) is True
    assert detect_harnesses(tmp_path) == ["opencode"]


def test_detect_claude_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )
    assert detect_harnesses(tmp_path) == ["claude"]


def test_detect_pi_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/pi" if name == "pi" else None,
    )
    assert detect_harnesses(tmp_path) == ["pi"]


def test_detect_harnesses_excludes_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda name: None)
    assert detect_harnesses(tmp_path) == []


def test_opencode_config_matches_hub_ui(tmp_path):
    HARNESSES["opencode"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / "opencode.json").read_text())
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["model"] == "skore/skore-agent"
    assert config["provider"]["skore"]["name"] == "Skore Hub"
    assert config["provider"]["skore"]["models"]["skore-agent"]["name"] == "Skore Agent"


def test_pi_config_matches_hub_ui(tmp_path):
    HARNESSES["pi"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / ".pi" / "agent" / "models.json").read_text())
    model = config["providers"]["skore"]["models"][0]
    assert model["id"] == "skore-agent"
    assert model["contextWindow"] == 200000


def test_launch_opencode_passes_model_flag(tmp_path, monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/opencode" if cmd == "opencode" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("opencode", tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["opencode", "-m", "skore/skore-agent"]


def test_launch_pi_passes_provider_and_model(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/pi" if cmd == "pi" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("pi", tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["pi", "--provider", "skore", "--model", "skore-agent"]
    assert "PI_CODING_AGENT_DIR" in captured["env"]


def test_launch_errors_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )
    monkeypatch.setattr(
        _harnesses.os,
        "execve",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        _harnesses.launch_harness("opencode", tmp_path)


def test_claude_config_matches_hub_ui(tmp_path):
    HARNESSES["claude"].configure(_ctx(tmp_path))
    config = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text()
    )
    env = config["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://hub.test"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret-key"
    assert env["ANTHROPIC_MODEL"] == "skore-agent"


def test_launch_claude_loads_settings_env(tmp_path, monkeypatch):
    HARNESSES["claude"].configure(_ctx(tmp_path))
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/claude" if cmd == "claude" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("claude", tmp_path, model_id="skore-agent")

    assert captured["argv"] == ["claude"]
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret-key"


def test_launch_claude_without_settings_uses_process_env(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/claude" if cmd == "claude" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("claude", tmp_path)

    assert "ANTHROPIC_AUTH_TOKEN" not in captured["env"]


def test_launch_harness_errors_when_not_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _harnesses.launch_harness("opencode", tmp_path)


def test_exec_harness_errors_when_executable_missing(monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _harnesses._exec_harness("opencode", ["opencode"])


def test_exec_harness_invokes_execve(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(
        _harnesses.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"
    )

    def fake_execve(executable, argv, env):
        recorded["executable"] = executable
        recorded["argv"] = argv
        recorded["env"] = env

    monkeypatch.setattr(_harnesses.os, "execve", fake_execve)
    _harnesses._exec_harness("opencode", ["opencode", "-m", "x"], env={"A": "B"})

    assert recorded["executable"] == "/usr/bin/opencode"
    assert recorded["argv"] == ["opencode", "-m", "x"]
    assert recorded["env"] == {"A": "B"}
