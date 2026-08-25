from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from skore_cli import _agents
from skore_cli._agents import (
    AGENTS,
    DEFAULT_AGENT,
    HARNESS_NAMES,
    SKILL_AGENT_NAMES,
    Agent,
    HarnessContext,
    get_harness,
    installed_harnesses,
    is_harness_installed,
    is_non_interactive,
    launch_harness,
    normalize_harness_name,
    resolve_skill_agent,
    resolve_targets,
)


def test_default_agent():
    assert DEFAULT_AGENT == "agents"


def test_agent_names_match_registry():
    assert SKILL_AGENT_NAMES == [
        "agents",
        "claude-code",
        "cursor",
        "codex",
        "gemini",
    ]


def test_harness_names_come_from_registry():
    assert HARNESS_NAMES == ["claude", "codex", "opencode", "pi", "copilot"]


def test_harness_rows_are_complete():
    harnesses = [agent for agent in AGENTS.values() if agent.harness_name]
    assert all(agent.configure is not None for agent in harnesses)
    assert all(agent.launch is not None for agent in harnesses)


def test_registry_values_are_agents():
    assert all(isinstance(agent, Agent) for agent in AGENTS.values())


def test_agent_is_frozen():
    agent = AGENTS["agents"]
    with pytest.raises(FrozenInstanceError):
        agent.name = "other"  # type: ignore[misc]


def test_resolve_targets_project_scope(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    targets = resolve_targets(["agents"], global_=False, home=home, cwd=project)

    assert targets == [("agents", project / ".agents" / "skills")]


def test_resolve_targets_global_scope(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    targets = resolve_targets(["cursor"], global_=True, home=home, cwd=project)

    assert targets == [("cursor", home / ".cursor" / "skills")]


def test_resolve_targets_gemini_differs_by_scope(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    local = resolve_targets(["gemini"], global_=False, home=home, cwd=project)
    global_ = resolve_targets(["gemini"], global_=True, home=home, cwd=project)

    assert local == [("gemini", project / ".agents" / "skills")]
    assert global_ == [("gemini", home / ".gemini" / "skills")]


def test_resolve_targets_deduplicates_by_directory(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    targets = resolve_targets(
        ["agents", "codex"], global_=False, home=home, cwd=project
    )

    assert targets == [("agents", project / ".agents" / "skills")]


def test_resolve_targets_uses_defaults(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(Path, "cwd", lambda: project)

    targets = resolve_targets(["agents"], global_=False)

    assert targets == [("agents", project / ".agents" / "skills")]


def test_harness_context_normalizes_hub_url():
    context = HarnessContext(Path("."), "http://hub.test///", "secret")

    assert context.base_url == "http://hub.test/v1"


def test_is_non_interactive_when_agent_is_detected(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(_agents, "detect_agent", lambda: AGENTS["opencode"])

    assert is_non_interactive() is True


def test_is_non_interactive_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "1")

    assert is_non_interactive() is True


def test_harness_display_name_uses_label():
    assert AGENTS["claude-code"].harness_display_name == "Claude"
    assert AGENTS["agents"].harness_display_name == "Agents"


def test_harness_registry_helpers(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )

    assert get_harness("opencode") is AGENTS["opencode"]
    with pytest.raises(KeyError):
        get_harness("missing")
    assert normalize_harness_name(None) is None
    assert normalize_harness_name("claude-code") == "claude"
    assert normalize_harness_name("unknown") == "unknown"
    assert is_harness_installed(AGENTS["opencode"])
    assert not is_harness_installed(AGENTS["claude-code"])
    assert installed_harnesses() == [AGENTS["opencode"]]


def test_resolve_skill_agent_requires_skill_directories():
    agent = Agent(name="broken", label="Broken")

    with pytest.raises(ValueError, match="has no skills target"):
        resolve_skill_agent(agent)


def test_launch_harness_validates_installation(monkeypatch, tmp_path):
    monkeypatch.setattr(_agents, "is_harness_installed", lambda agent: False)
    with pytest.raises(RuntimeError, match="Claude is not installed"):
        launch_harness(AGENTS["claude-code"], tmp_path)


def test_launch_harness_requires_launcher(monkeypatch, tmp_path):
    agent = Agent(name="fake", label="Fake", harness_name="fake")
    monkeypatch.setattr(_agents, "is_harness_installed", lambda selected: True)

    with pytest.raises(RuntimeError, match="has no harness launcher"):
        launch_harness(agent, tmp_path)


def test_launch_harness_delegates_to_launcher(monkeypatch, tmp_path):
    calls = []
    agent = Agent(
        name="fake",
        label="Fake",
        harness_name="fake",
        launch=lambda workspace, model_id: calls.append((workspace, model_id)),
    )
    monkeypatch.setattr(_agents, "is_harness_installed", lambda selected: True)

    launch_harness(agent, tmp_path, model_id="custom-model")

    assert calls == [(tmp_path, "custom-model")]
