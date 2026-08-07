"""Tests for the ``skore agent`` command and ``.skore`` persistence."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
import rich_click as click
from click.testing import CliRunner

from skore_cli.agent import _client, _commands, _harnesses
from skore_cli.agent import app as _agent_app
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


def test_skore_config_load_returns_none_when_absent(tmp_path):
    assert SkoreConfig.load(tmp_path) is None


def test_skore_config_load_returns_none_when_required_field_missing(tmp_path):
    (tmp_path / SKORE_FILENAME).write_text(
        json.dumps({"hub_url": "http://hub.test", "workspace": "ws-1"}) + "\n"
    )
    assert SkoreConfig.load(tmp_path) is None


def test_skore_config_save_omits_none_harness(tmp_path):
    config = SkoreConfig(
        hub_url="http://hub.test",
        workspace="ws-1",
        workspace_id=1,
        api_key="secret",
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
    assert ".skore" in (tmp_path / ".gitignore").read_text().splitlines()


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


# --------------------------------------------------------------------------- #
# _is_interactive
# --------------------------------------------------------------------------- #


def test_is_interactive_requires_both_streams(monkeypatch):
    monkeypatch.setattr(_commands.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(_commands.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    assert _commands._is_interactive() is True

    monkeypatch.setattr(_commands.sys, "stdout", SimpleNamespace(isatty=lambda: False))
    assert _commands._is_interactive() is False


# --------------------------------------------------------------------------- #
# _ensure_login
# --------------------------------------------------------------------------- #


def test_ensure_login_delegates_to_hub_auth(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        _commands, "ensure_login", lambda *, timeout: seen.setdefault("t", timeout)
    )
    _commands._ensure_login("http://hub.test", timeout=42)
    assert seen["t"] == 42


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
    monkeypatch.setattr(_commands, "detect_harnesses", lambda ws: ["opencode", "pi"])
    monkeypatch.setattr(_agent_app, "HarnessPicker", _FakePicker("pi"))

    assert _commands._pick_harness(tmp_path) == "pi"


def test_pick_harness_errors_when_none_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(_commands, "detect_harnesses", lambda ws: [])
    with pytest.raises(click.ClickException, match="no supported harness"):
        _commands._pick_harness(tmp_path)


def test_pick_harness_aborts_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(_commands, "detect_harnesses", lambda ws: ["opencode"])
    monkeypatch.setattr(_agent_app, "HarnessPicker", _FakePicker(None))
    with pytest.raises(click.Abort):
        _commands._pick_harness(tmp_path)


# --------------------------------------------------------------------------- #
# _resolve_membership
# --------------------------------------------------------------------------- #


def test_resolve_membership_single_membership_auto_selected():
    only = _membership("ws-1")
    assert _commands._resolve_membership([only], None) is only


def test_resolve_membership_matches_saved_workspace():
    memberships = [_membership("ws-1"), _membership("ws-2", workspace_id=2)]
    assert _commands._resolve_membership(memberships, "ws-2").public_id == "ws-2"


def test_resolve_membership_unknown_workspace_errors():
    with pytest.raises(click.ClickException, match="not in your memberships"):
        _commands._resolve_membership([_membership("ws-1")], "ws-missing")


def test_resolve_membership_multiple_non_interactive_errors(monkeypatch):
    monkeypatch.setattr(_commands, "_is_interactive", lambda: False)
    memberships = [_membership("ws-1"), _membership("ws-2", workspace_id=2)]
    with pytest.raises(click.UsageError, match="run interactively"):
        _commands._resolve_membership(memberships, None)


def test_resolve_membership_multiple_interactive_picks(monkeypatch):
    monkeypatch.setattr(_commands, "_is_interactive", lambda: True)
    memberships = [_membership("ws-1"), _membership("ws-2", workspace_id=2)]
    monkeypatch.setattr(_commands, "_pick_workspace", lambda m: m[1])
    assert _commands._resolve_membership(memberships, None).public_id == "ws-2"


# --------------------------------------------------------------------------- #
# _create_workspace_api_key
# --------------------------------------------------------------------------- #


def test_create_workspace_api_key_mints_secret(monkeypatch):
    monkeypatch.setattr(_commands._client, "list_api_keys", lambda *a, **k: [])
    captured = {}

    def fake_create(hub_url, token, user_id, **kwargs):
        captured.update(kwargs)
        return 7, "the-secret"

    monkeypatch.setattr(_commands._client, "create_api_key", fake_create)

    secret = _commands._create_workspace_api_key(
        "http://hub.test", "tok", "user-1", _membership(), "opencode"
    )

    assert secret == "the-secret"
    assert captured["name"] == "opencode"
    assert set(captured["permissions"]) == set(_commands.PROJECT_PERMISSIONS)


def test_create_workspace_api_key_requires_permissions():
    membership = _client.Membership(
        workspace_id=1, public_id="ws-1", permissions=frozenset()
    )
    with pytest.raises(click.ClickException, match="cannot create project API keys"):
        _commands._create_workspace_api_key(
            "http://hub.test", "tok", "user-1", membership, "opencode"
        )


def test_create_workspace_api_key_dedupes_name_within_workspace(monkeypatch):
    existing = [
        _client.ApiKeyInfo(
            id=1,
            name="opencode",
            workspace_id=1,
            created_at=None,
            expires_at=None,
        )
    ]
    monkeypatch.setattr(_commands._client, "list_api_keys", lambda *a, **k: existing)
    captured = {}

    def fake_create(hub_url, token, user_id, **kwargs):
        captured.update(kwargs)
        return 2, "secret"

    monkeypatch.setattr(_commands._client, "create_api_key", fake_create)

    _commands._create_workspace_api_key(
        "http://hub.test", "tok", "user-1", _membership(), "opencode"
    )

    assert captured["name"] == "opencode-2"


# --------------------------------------------------------------------------- #
# agent command: extra branches
# --------------------------------------------------------------------------- #


def test_agent_no_memberships_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: "http://hub.test"
    )
    monkeypatch.setattr(_commands, "_ensure_login", lambda hub_url, timeout: "tok")
    monkeypatch.setattr(_commands._client, "me", lambda hub_url, token: ("user-1", []))

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code != 0
    assert "not a member of any hub workspace" in _plain_output(result.output)


def test_agent_errors_when_harness_not_installed(tmp_path, monkeypatch):
    _write_skore(tmp_path)
    monkeypatch.setattr(_harnesses.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: url or "http://hub.test"
    )

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code != 0
    assert "not installed or not on PATH" in _plain_output(result.output)


def test_agent_valid_config_without_harness_non_interactive_errors(
    tmp_path, monkeypatch
):
    # Config is complete (api_key + workspace) but no harness was ever saved.
    payload = {
        "hub_url": "http://hub.test",
        "workspace": "ws-1",
        "workspace_id": 1,
        "api_key": "secret-key",
    }
    (tmp_path / SKORE_FILENAME).write_text(json.dumps(payload) + "\n")
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: url or "http://hub.test"
    )
    monkeypatch.setattr(_commands, "_is_interactive", lambda: False)

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code != 0
    assert "pass --harness" in _plain_output(result.output)


def test_agent_valid_config_without_harness_picks_interactively(tmp_path, monkeypatch):
    payload = {
        "hub_url": "http://hub.test",
        "workspace": "ws-1",
        "workspace_id": 1,
        "api_key": "secret-key",
    }
    (tmp_path / SKORE_FILENAME).write_text(json.dumps(payload) + "\n")
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: url or "http://hub.test"
    )
    monkeypatch.setattr(_commands, "_is_interactive", lambda: True)
    monkeypatch.setattr(_commands, "_pick_harness", lambda workspace: "opencode")
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda name, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"


def test_agent_first_run_picks_harness_interactively(tmp_path, monkeypatch):
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: "http://hub.test"
    )
    monkeypatch.setattr(_commands, "_ensure_login", lambda hub_url, timeout: "tok")
    monkeypatch.setattr(
        _commands._client, "me", lambda hub_url, token: ("user-1", [_membership()])
    )
    monkeypatch.setattr(_commands, "_is_interactive", lambda: True)
    monkeypatch.setattr(_commands, "_pick_harness", lambda workspace: "opencode")
    monkeypatch.setattr(_commands._client, "list_api_keys", lambda *a, **k: [])
    monkeypatch.setattr(
        _commands._client, "create_api_key", lambda *a, **k: (1, "new-secret")
    )
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda name, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(agent, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"
    assert saved["api_key"] == "new-secret"


def test_agent_rewrites_config_when_harness_changes(tmp_path, monkeypatch):
    _write_skore(tmp_path, harness="claude")
    _mock_harness_on_path(monkeypatch, "opencode")
    monkeypatch.setattr(
        _commands, "resolve_hub_uri", lambda url, *a, **k: url or "http://hub.test"
    )
    monkeypatch.setattr(
        _commands,
        "launch_harness",
        lambda name, workspace, model_id=DEFAULT_MODEL_ID: None,
    )

    result = CliRunner().invoke(
        agent, ["--workspace", str(tmp_path), "--harness", "opencode"]
    )

    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / SKORE_FILENAME).read_text())
    assert saved["harness"] == "opencode"
