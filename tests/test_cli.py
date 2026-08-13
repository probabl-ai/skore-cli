"""Tests for the CLI wiring, the lazy `skore` accessor and the plugin host."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import rich_click as click

from skore_cli import _plugins, _skore


def test_cli_exposes_builtin_commands():
    from skore_cli import cli

    assert {"skills", "agent", "sync"} <= set(cli.commands)


def test_cli_without_subcommand_shows_plain_help():
    from click.testing import CliRunner

    from skore_cli import cli

    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Skore command-line interface." in result.output
    assert "agent" in result.output
    assert "skills" in result.output
    assert "Quick start:" in result.output


# --------------------------------------------------------------------------- #
# Agent detection: help output
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


def test_cli_help_no_agent_shows_generic_quick_start(monkeypatch):
    from click.testing import CliRunner

    from skore_cli import cli

    _clear_agent_envs(monkeypatch)
    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Detected:" not in result.output
    assert "Install all skills" in result.output
    assert "Configure and launch" in result.output


def test_cli_interactive_without_subcommand_prints_help(monkeypatch):
    from click.testing import CliRunner

    from skore_cli import cli

    monkeypatch.setattr("skore_cli.is_non_interactive", lambda: False)
    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_cli_help_claude_code_detected(monkeypatch):
    from click.testing import CliRunner

    from skore_cli import cli

    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Detected: Claude Code" in result.output
    assert "Skills target: .claude/skills" in result.output
    assert "Harness: Claude" in result.output
    assert ".claude/skills" in result.output
    assert "Configure Claude with the Skore Hub provider" in result.output


def test_cli_help_cursor_detected(monkeypatch):
    from click.testing import CliRunner

    from skore_cli import cli

    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("CURSOR_AGENT", "1")
    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Detected: Cursor" in result.output
    assert "Skills target: .cursor/skills" in result.output
    assert "Harness:" not in result.output


def test_cli_help_opencode_detected(monkeypatch):
    from click.testing import CliRunner

    from skore_cli import cli

    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("OPENCODE_CLIENT", "1")
    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Detected: OpenCode" in result.output
    assert "Harness: OpenCode" in result.output
    assert "Skills target: .agents/skills" in result.output
    assert "Configure OpenCode with the Skore Hub provider" in result.output


def test_cli_help_pi_detected(monkeypatch):
    from click.testing import CliRunner

    from skore_cli import cli

    _clear_agent_envs(monkeypatch)
    monkeypatch.setenv("PI_CODING_AGENT", "true")
    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Detected: Pi" in result.output
    assert "Harness: Pi" in result.output
    assert "Skills target: .agents/skills" in result.output


def test_cli_subcommand_help_omits_banner():
    from click.testing import CliRunner

    from skore_cli import cli
    from skore_cli._style import SKORE_BANNER

    result = CliRunner().invoke(cli, ["skills"])

    assert result.exit_code == 0
    assert SKORE_BANNER.rstrip("\n") not in result.output
    assert "Usage" in result.output


# --------------------------------------------------------------------------- #
# _skore.auth
# --------------------------------------------------------------------------- #


def test_auth_returns_module(monkeypatch):
    sentinel = SimpleNamespace(name="fake-module")
    monkeypatch.setattr(_skore.importlib, "import_module", lambda name: sentinel)

    assert _skore.auth("uri") is sentinel


def test_auth_imports_expected_path(monkeypatch):
    seen = {}

    def fake_import(name):
        seen["name"] = name
        return SimpleNamespace()

    monkeypatch.setattr(_skore.importlib, "import_module", fake_import)

    _skore.auth("token")
    assert seen["name"] == "skore._plugins.hub.authentication.token"


def test_auth_missing_skore_raises_click_exception(monkeypatch):
    def fake_import(name):
        raise ImportError("no skore")

    monkeypatch.setattr(_skore.importlib, "import_module", fake_import)

    with pytest.raises(click.ClickException) as excinfo:
        _skore.auth("store")
    assert "skore" in str(excinfo.value)


def test_resolve_hub_uri_sets_explicit_url(monkeypatch):
    module = SimpleNamespace(URI=lambda: "https://resolved.test")

    monkeypatch.delenv(_skore.URI_ENV, raising=False)

    assert _skore.resolve_hub_uri("https://hub.test", lambda _: module) == (
        "https://resolved.test"
    )
    assert os.environ[_skore.URI_ENV] == "https://hub.test"


# --------------------------------------------------------------------------- #
# _plugins.load_plugins
# --------------------------------------------------------------------------- #


class _FakeEntryPoint:
    def __init__(self, name, loader):
        self.name = name
        self._loader = loader

    def load(self):
        return self._loader()


def _group():
    @click.group()
    def cli():  # pragma: no cover - never invoked
        ...

    return cli


def _patch_entry_points(monkeypatch, entry_points):
    monkeypatch.setattr(_plugins, "_iter_plugin_entry_points", lambda: entry_points)


def test_load_plugins_attaches_command(monkeypatch):
    @click.command("plugged")
    def plugged():  # pragma: no cover - never invoked
        ...

    _patch_entry_points(monkeypatch, [_FakeEntryPoint("plugged", lambda: plugged)])
    group = _group()
    _plugins.load_plugins(group)

    assert "plugged" in group.commands


def test_load_plugins_accepts_zero_arg_callable(monkeypatch):
    @click.command("made")
    def made():  # pragma: no cover - never invoked
        ...

    # The loaded object is a factory returning the command.
    _patch_entry_points(monkeypatch, [_FakeEntryPoint("made", lambda: lambda: made)])
    group = _group()
    _plugins.load_plugins(group)

    assert "made" in group.commands


def test_load_plugins_survives_load_error(monkeypatch, capsys):
    def boom():
        raise RuntimeError("kaboom")

    _patch_entry_points(monkeypatch, [_FakeEntryPoint("broken", boom)])
    group = _group()

    _plugins.load_plugins(group)  # must not raise

    assert group.commands == {}
    err = capsys.readouterr().err
    assert "broken" in err
    assert "kaboom" in err


def test_load_plugins_skips_non_command(monkeypatch, capsys):
    _patch_entry_points(
        monkeypatch, [_FakeEntryPoint("weird", lambda: lambda: "not-a-command")]
    )
    group = _group()

    _plugins.load_plugins(group)

    assert group.commands == {}
    assert "did not return a click command" in capsys.readouterr().err
