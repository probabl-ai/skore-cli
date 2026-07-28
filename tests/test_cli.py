"""Tests for the CLI wiring, the lazy `skore` accessor and the plugin host."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import rich_click as click

from skore_cli import _plugins, _skore


def test_cli_exposes_builtin_commands():
    from skore_cli import cli

    assert {"skills", "agent"} <= set(cli.commands)


def test_cli_without_subcommand_prints_banner_before_help():
    from click.testing import CliRunner

    from skore_cli import cli
    from skore_cli._style import SKORE_BANNER

    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    banner = SKORE_BANNER.rstrip("\n")
    assert banner in result.output
    assert result.output.index(banner) < result.output.index("Usage")
    assert "agent" in result.output
    assert "skills" in result.output


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
