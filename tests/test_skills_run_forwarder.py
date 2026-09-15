"""Tests for ``skore skills run`` forwarding to ``python -m skore_skills``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from skore_cli import cli
from skore_cli.skills import _run as run_mod


def _invoke(args, **kwargs):
    return CliRunner().invoke(cli, args, **kwargs)


class _Result:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_skore_run_is_not_a_command() -> None:
    """``skore run`` is not a top-level command."""
    result = _invoke(["run"])
    assert result.exit_code != 0
    assert "run" not in cli.commands


def test_forwards_argv_to_skore_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``skills run api get X`` becomes ``python -m skore_skills api get X``."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_mod.shutil, "which", lambda _name: None)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> _Result:
        calls.append(list(argv))
        return _Result(0)

    monkeypatch.setattr(run_mod.subprocess, "run", fake_run)
    result = _invoke(["skills", "run", "api", "get", "X"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert calls[0][-2:] == ["-c", "import skore_skills"]
    assert calls[1][-5:] == ["-m", "skore_skills", "api", "get", "X"]


def test_missing_module_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed import probe prints an install hint, not a traceback-only failure."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_mod.shutil, "which", lambda _name: None)

    def fake_run(argv: list[str], **kwargs: Any) -> _Result:
        return _Result(1)

    monkeypatch.setattr(run_mod.subprocess, "run", fake_run)
    result = _invoke(["skills", "run", "status"])
    assert result.exit_code == 1
    assert "skore-skills is not installed" in result.output


def test_pixi_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pixi.toml project is dispatched via ``pixi run python``."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pixi.toml").write_text('[workspace]\nname = "demo"\n')
    monkeypatch.setattr(run_mod.shutil, "which", lambda name: "/usr/bin/pixi")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> _Result:
        calls.append(list(argv))
        return _Result(0)

    monkeypatch.setattr(run_mod.subprocess, "run", fake_run)
    result = _invoke(["skills", "run", "status"])
    assert result.exit_code == 0, result.output
    assert calls[0][:3] == ["/usr/bin/pixi", "run", "python"]
    assert calls[1][:4] == ["/usr/bin/pixi", "run", "python", "-m"]


def test_pixi_environment_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``PIXI_ENVIRONMENT`` is passed as ``pixi run -e``."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pixi.toml").write_text('[workspace]\nname = "demo"\n')
    monkeypatch.setenv("PIXI_ENVIRONMENT", "agent")
    monkeypatch.setattr(run_mod.shutil, "which", lambda name: "/usr/bin/pixi")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> _Result:
        calls.append(list(argv))
        return _Result(0)

    monkeypatch.setattr(run_mod.subprocess, "run", fake_run)
    result = _invoke(["skills", "run", "--help"])
    assert result.exit_code == 0, result.output
    assert calls[0][:5] == ["/usr/bin/pixi", "run", "-e", "agent", "python"]


def test_workspace_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--workspace`` sets the project root used for pixi detection."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pixi.toml").write_text('[workspace]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_mod.shutil, "which", lambda name: "/usr/bin/pixi")
    cwds: list[Path] = []

    def fake_run(argv: list[str], **kwargs: Any) -> _Result:
        cwds.append(Path(kwargs["cwd"]))
        return _Result(0)

    monkeypatch.setattr(run_mod.subprocess, "run", fake_run)
    result = _invoke(["skills", "run", "--workspace", str(project), "status"])
    assert result.exit_code == 0, result.output
    assert cwds
    assert cwds[0] == project


def test_forwards_skore_skills_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero ``skore_skills`` exit is propagated."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_mod.shutil, "which", lambda _name: None)
    n = {"i": 0}

    def fake_run(argv: list[str], **kwargs: Any) -> _Result:
        n["i"] += 1
        if n["i"] == 1:
            return _Result(0)
        return _Result(3)

    monkeypatch.setattr(run_mod.subprocess, "run", fake_run)
    result = _invoke(["skills", "run", "check", "workspace"])
    assert result.exit_code == 3
