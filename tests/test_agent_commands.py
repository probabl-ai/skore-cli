"""Tests for the ``skore agent`` command and ``.skore`` persistence."""

from __future__ import annotations

import json
import os
import re
from types import SimpleNamespace

import pytest
import rich_click as click
from click.testing import CliRunner

from skore_cli import _agents
from skore_cli._agents import AGENTS, DEFAULT_MODEL_ID, HARNESS_NAMES, HarnessContext
from skore_cli.agent import _commands
from skore_cli.agent import app as _agent_app
from skore_cli.agent._commands import agent
from skore_cli.agent._skore_file import (
    SKORE_FILENAME,
    SkoreConfig,
    ensure_gitignore_entry,
)
from skore_cli.hub import _client
from skore_cli.hub._commands import PROJECT_PERMISSIONS

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _plain_output(output: str) -> str:
    """Strip ANSI codes from rich-click panels for stable assertions."""
    return _ANSI_ESCAPE.sub("", output)


def _mock_harness_on_path(monkeypatch, name: str) -> None:
    """Pretend the harness binary is installed without relying on the real PATH."""
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd == name else None,
    )


def _membership(public_id: str = "ws-1", workspace_id: int = 1):
    return _client.Membership(
        workspace_id=workspace_id,
        public_id=public_id,
        permissions=frozenset(PROJECT_PERMISSIONS),
    )


@pytest.fixture(autouse=True)
def stub_registry(monkeypatch):
    """Serve a stored API key so runs never reach the real credential registry."""
    monkeypatch.setattr(
        _commands,
        "_registry",
        lambda: SimpleNamespace(get=lambda **kwargs: "new-secret"),
    )


@pytest.fixture(autouse=True)
def default_hub_uri(monkeypatch):
    """Seed the hub URI so first-run `URI()` does not hit the public hub."""
    monkeypatch.setenv("SKORE_HUB_URI", "http://hub.test")


def _write_skore(directory, **overrides):
    payload = {
        "hub_url": "http://hub.test",
        "workspace": "ws-1",
        "workspace_id": 1,
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
        harness="pi",
    )
    path = config.save(tmp_path)
    loaded = SkoreConfig.load(tmp_path)
    assert path.name == SKORE_FILENAME
    assert loaded == config


def test_skore_config_load_sets_hub_uri_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SKORE_HUB_URI", raising=False)
    _write_skore(tmp_path)
    SkoreConfig.load(tmp_path)
    assert os.environ["SKORE_HUB_URI"] == "http://hub.test"


def test_skore_config_load_invalid_returns_none(tmp_path):
    (tmp_path / SKORE_FILENAME).write_text("{ not json")
    assert SkoreConfig.load(tmp_path) is None


def test_skore_config_load_normalizes_legacy_claude_code_harness(tmp_path):
    _write_skore(tmp_path, harness="claude-code")
    loaded = SkoreConfig.load(tmp_path)
    assert loaded is not None
    assert loaded.harness == "claude"


def test_skore_config_load_returns_none_when_absent(tmp_path):
    assert SkoreConfig.load(tmp_path) is None


def test_skore_config_load_returns_none_when_required_field_missing(tmp_path):
    (tmp_path / SKORE_FILENAME).write_text(
        json.dumps({"hub_url": "http://hub.test"}) + "\n"
    )
    assert SkoreConfig.load(tmp_path) is None


def test_skore_config_save_omits_the_api_key(tmp_path):
    SkoreConfig(hub_url="http://hub.test", workspace="ws-1", workspace_id=1).save(
        tmp_path
    )
    payload = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert "api_key" not in payload


def test_skore_config_save_omits_none_harness(tmp_path):
    config = SkoreConfig(
        hub_url="http://hub.test",
        workspace="ws-1",
        workspace_id=1,
    )
    config.save(tmp_path)
    payload = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert "harness" not in payload


def test_ensure_gitignore_appends_to_existing_file(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\n__pycache__/\n")
    ensure_gitignore_entry(tmp_path)
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines[-1] == ".skore"
    assert "*.log" in lines


def test_ensure_gitignore_inserts_blank_line_when_missing_trailing_newline(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log")
    ensure_gitignore_entry(tmp_path)
    assert (tmp_path / ".gitignore").read_text() == "*.log\n\n.skore\n"


def test_ensure_gitignore_keeps_existing_trailing_blank_line(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\n\n")
    ensure_gitignore_entry(tmp_path)
    assert (tmp_path / ".gitignore").read_text() == "*.log\n\n.skore\n"


def test_ensure_gitignore_appends_entry(tmp_path):
    ensure_gitignore_entry(tmp_path)
    assert (tmp_path / ".gitignore").read_text().strip() == ".skore"

    ensure_gitignore_entry(tmp_path)
    assert (tmp_path / ".gitignore").read_text().count(".skore") == 1


def test_opencode_writer_embeds_api_key(tmp_path):
    AGENTS["opencode"].configure(
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


def test_agent_invalid_harness_lists_all_supported_harnesses(tmp_path):
    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "does-not-exist"]
    )
    assert result.exit_code != 0
    output = _plain_output(result.output)
    for name in HARNESS_NAMES:
        assert name in output


def test_agent_uses_existing_skore_config(tmp_path, monkeypatch):
    _write_skore(tmp_path)
    _mock_harness_on_path(monkeypatch, "opencode")
    launched: list[str] = []
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: launched.append(
            selected.harness_name
        ),
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
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client,
        "me",
        lambda hub_url, token: ("user-1", [_membership()]),
    )
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(
        agent,
        ["--workspace", str(tmp_path), "--harness", "opencode"],
    )

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["workspace"] == "ws-1"
    assert saved["hub_url"] == "http://hub.test"
    assert "api_key" not in saved
    assert ".skore" in (tmp_path / ".gitignore").read_text().splitlines()


@pytest.mark.parametrize("harness_flag", ["bob-ide", "bobide"])
def test_agent_bob_ide_first_run_on_linux_writes_mcp_config(
    tmp_path, monkeypatch, harness_flag
):
    """Bob IDE on Linux installs a ``bobide`` binary on PATH (not ``bob-ide``);
    the run must detect it and still write ``.bob/mcp.json`` after saving
    ``.skore`` (skore-hub#1894). ``--harness bobide`` is accepted as an alias
    and stored under the canonical ``bob-ide`` name."""
    monkeypatch.setattr(_agents.sys, "platform", "linux")
    _mock_harness_on_path(monkeypatch, "bobide")
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client,
        "me",
        lambda hub_url, token: ("user-1", [_membership()]),
    )
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", harness_flag]
    )

    assert result.exit_code == 0, result.output
    assert "not installed or not on PATH" not in _plain_output(result.output)
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "bob-ide"
    mcp = json.loads((tmp_path / ".bob" / "mcp.json").read_text())
    assert mcp["mcpServers"]["skore"]["url"] == "http://hub.test/mcp"


def test_agent_non_interactive_without_harness_errors(tmp_path, monkeypatch):
    _clear_agent_envs(monkeypatch)
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client,
        "me",
        lambda hub_url, token: ("user-1", [_membership()]),
    )
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code != 0
    assert "pass --harness" in _plain_output(result.output)


def test_agent_generates_api_key_when_none_is_stored(tmp_path, monkeypatch):
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client, "me", lambda hub_url, token: ("user-1", [_membership()])
    )
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    stored: dict[tuple[str, str], str] = {}
    generated = []

    def fake_generate(*, host, workspace, name, login_timeout):
        generated.append((host, workspace))
        stored[(host, workspace)] = "minted-secret"

    monkeypatch.setattr(
        _commands,
        "_registry",
        lambda: SimpleNamespace(
            get=lambda *, host, workspace: stored.get((host, workspace))
        ),
    )
    monkeypatch.setattr(_commands, "generate", fake_generate)

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code == 0, result.output
    assert generated == [("http://hub.test", "ws-1")]
    provider = json.loads((tmp_path / "opencode.json").read_text())["provider"]
    assert provider["skore"]["options"]["apiKey"] == "minted-secret"


# --------------------------------------------------------------------------- #
# is_non_interactive
# --------------------------------------------------------------------------- #


def test_is_non_interactive_with_tty(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(_agents, "detect_agent", lambda: None)
    monkeypatch.setattr(_agents.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(_agents.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    assert _commands.is_non_interactive() is False


def test_is_non_interactive_without_tty(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(_agents, "detect_agent", lambda: None)
    monkeypatch.setattr(_agents.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(_agents.sys, "stdout", SimpleNamespace(isatty=lambda: False))
    assert _commands.is_non_interactive() is True


# --------------------------------------------------------------------------- #
# _pick_workspace
# --------------------------------------------------------------------------- #


class _FakePicker:
    """Stand-in for the Textual pickers: ``run()`` is a no-op, ``result`` is set."""

    def __init__(self, result):
        self._result = result

    def __call__(self, *args, **kwargs):
        self.result = self._result
        return self

    def run(self):
        return None


def test_pick_workspace_returns_selected_membership(monkeypatch):
    memberships = [_membership("ws-1"), _membership("ws-2", workspace_id=2)]
    monkeypatch.setattr(_agent_app, "WorkspacePicker", _FakePicker("ws-2"))

    chosen = _commands._pick_workspace(memberships)

    assert chosen.public_id == "ws-2"


def test_pick_workspace_aborts_when_cancelled(monkeypatch):
    monkeypatch.setattr(_agent_app, "WorkspacePicker", _FakePicker(None))
    with pytest.raises(click.Abort):
        _commands._pick_workspace([_membership()])


# --------------------------------------------------------------------------- #
# _pick_harness
# --------------------------------------------------------------------------- #


def test_pick_harness_returns_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _commands,
        "installed_harnesses",
        lambda: [AGENTS["opencode"], AGENTS["pi"]],
    )
    monkeypatch.setattr(_agent_app, "HarnessPicker", _FakePicker("pi"))

    assert _commands._pick_harness(tmp_path) == "pi"


def test_pick_harness_errors_when_none_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(_commands, "installed_harnesses", lambda: [])
    with pytest.raises(click.ClickException, match="no supported harness"):
        _commands._pick_harness(tmp_path)


def test_pick_harness_aborts_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(_commands, "installed_harnesses", lambda: [AGENTS["opencode"]])
    monkeypatch.setattr(_agent_app, "HarnessPicker", _FakePicker(None))
    with pytest.raises(click.Abort):
        _commands._pick_harness(tmp_path)


# --------------------------------------------------------------------------- #
# _resolve_membership
# --------------------------------------------------------------------------- #


def test_resolve_membership_single_membership_auto_selected():
    only = _membership("ws-1")
    assert _commands._resolve_membership([only]) is only


def test_resolve_membership_multiple_non_interactive_errors(monkeypatch):
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)
    memberships = [_membership("ws-1"), _membership("ws-2", workspace_id=2)]
    with pytest.raises(click.UsageError, match="run interactively"):
        _commands._resolve_membership(memberships)


def test_resolve_membership_multiple_interactive_picks(monkeypatch):
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: False)
    memberships = [_membership("ws-1"), _membership("ws-2", workspace_id=2)]
    monkeypatch.setattr(_commands, "_pick_workspace", lambda m: m[1])
    assert _commands._resolve_membership(memberships).public_id == "ws-2"


# --------------------------------------------------------------------------- #
# agent command: extra branches
# --------------------------------------------------------------------------- #


def test_agent_no_memberships_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(_commands._client, "me", lambda hub_url, token: ("user-1", []))

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code != 0
    assert "not a member of any hub workspace" in _plain_output(result.output)


def test_agent_errors_when_harness_not_installed(tmp_path, monkeypatch):
    _write_skore(tmp_path)
    monkeypatch.setattr(_agents.shutil, "which", lambda cmd: None)
    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code != 0
    assert "not installed or not on PATH" in _plain_output(result.output)


def test_agent_valid_config_without_harness_non_interactive_errors(
    tmp_path, monkeypatch
):
    # Config is complete (hub_url + workspace) but no harness was ever saved.
    _clear_agent_envs(monkeypatch)
    payload = {
        "hub_url": "http://hub.test",
        "workspace": "ws-1",
        "workspace_id": 1,
    }
    (tmp_path / SKORE_FILENAME).write_text(json.dumps(payload) + "\n")
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code != 0
    assert "pass --harness" in _plain_output(result.output)


def test_agent_valid_config_without_harness_picks_interactively(tmp_path, monkeypatch):
    payload = {
        "hub_url": "http://hub.test",
        "workspace": "ws-1",
        "workspace_id": 1,
    }
    (tmp_path / SKORE_FILENAME).write_text(json.dumps(payload) + "\n")
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: False)
    monkeypatch.setattr(_commands, "_pick_harness", lambda workspace: "opencode")
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"


def test_agent_first_run_picks_harness_interactively(tmp_path, monkeypatch):
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client, "me", lambda hub_url, token: ("user-1", [_membership()])
    )
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: False)
    monkeypatch.setattr(_commands, "_pick_harness", lambda workspace: "opencode")
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"


def test_agent_rewrites_config_when_harness_changes(tmp_path, monkeypatch):
    _write_skore(tmp_path, harness="claude")
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"


# --------------------------------------------------------------------------- #
# Agent detection: non-interactive harness auto-selection
# --------------------------------------------------------------------------- #

_AGENT_ENV_VARS = (
    "CLAUDECODE",
    "CURSOR_AGENT",
    "GEMINI_CLI",
    "CODEX_SANDBOX",
    "PI_CODING_AGENT",
    "OPENCODE_CLIENT",
    "CI",
)


def _clear_agent_envs(monkeypatch):
    for var in _AGENT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_agent_non_interactive_auto_selects_claude(tmp_path, monkeypatch):
    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    _mock_harness_on_path(monkeypatch, "claude")
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client, "me", lambda hub_url, token: ("user-1", [_membership()])
    )
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)
    launched = []
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: launched.append(
            selected.harness_name
        ),
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "claude"
    assert launched == []
    assert "configured with the Skore Hub" in _plain_output(result.output)


def test_agent_non_interactive_auto_selects_opencode(tmp_path, monkeypatch):
    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("OPENCODE_CLIENT", "1")
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client, "me", lambda hub_url, token: ("user-1", [_membership()])
    )
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)
    launched = []
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: launched.append(
            selected.harness_name
        ),
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"
    assert launched == []


def test_agent_non_interactive_auto_selects_pi(tmp_path, monkeypatch):
    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("PI_CODING_AGENT", "true")
    _mock_harness_on_path(monkeypatch, "pi")
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client, "me", lambda hub_url, token: ("user-1", [_membership()])
    )
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)
    launched = []
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: launched.append(
            selected.harness_name
        ),
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "pi"
    assert launched == []


def test_agent_non_interactive_detected_harness_not_on_path_errors(
    tmp_path, monkeypatch
):
    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(_agents.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(
        _commands, "login", lambda *, timeout: SimpleNamespace(access="tok")
    )
    monkeypatch.setattr(
        _commands._client, "me", lambda hub_url, token: ("user-1", [_membership()])
    )
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code != 0
    assert "pass --harness" in _plain_output(result.output)


def test_agent_detected_different_harness_still_launches(tmp_path, monkeypatch):
    """Claude detected but --harness opencode explicitly -> launches opencode."""
    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    _mock_harness_on_path(monkeypatch, "opencode")
    _write_skore(tmp_path)
    launched = []
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: launched.append(
            selected.harness_name
        ),
    )

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code == 0, result.output
    assert launched == ["opencode"]


def test_agent_reuse_path_auto_selects_detected_harness(tmp_path, monkeypatch):
    """Config exists but no harness; non-interactive + detected."""
    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("OPENCODE_CLIENT", "1")
    payload = {
        "hub_url": "http://hub.test",
        "workspace": "ws-1",
        "workspace_id": 1,
    }
    (tmp_path / SKORE_FILENAME).write_text(json.dumps(payload) + "\n")
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(_commands, "is_non_interactive", lambda: True)
    launched = []
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda selected, workspace, model_id=DEFAULT_MODEL_ID: launched.append(
            selected.harness_name
        ),
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"
    assert launched == []
