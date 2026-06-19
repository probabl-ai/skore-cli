"""Tests for ``skore agent model`` commands (status, install guards, skills).

These complement ``test_agent_workspace.py`` (which already covers the opencode
writer, the install marker and ``_resolve_hub_workspace``) without duplicating it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from click.testing import CliRunner

from skore_cli.agent._harnesses import MARKER_FILENAME, Credential
from skore_cli.agent.model import _commands
from skore_cli.agent.model._commands import install, status


def _write_marker(directory, **overrides):
    marker = {
        "harness": "opencode",
        "hub_url": "http://hub.test",
        "base_url": "http://hub.test/v1",
        "hub_workspace": "ws-1",
        "model_id": "skore-agent",
        "auth": "bearer",
        "session_binding": "plugin",
    }
    marker.update(overrides)
    (directory / MARKER_FILENAME).write_text(json.dumps(marker) + "\n")
    return marker


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


def test_status_missing_marker_errors(tmp_path):
    result = CliRunner().invoke(status, ["--workspace", str(tmp_path)])

    assert result.exit_code != 0
    assert "run `skore agent model install`" in result.output


def test_status_prints_marker_fields(tmp_path):
    _write_marker(tmp_path)

    result = CliRunner().invoke(status, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "opencode" in result.output
    assert "http://hub.test/v1" in result.output
    assert "skore-agent" in result.output
    assert "ws-1" in result.output


def test_status_counts_local_skills(tmp_path):
    _write_marker(tmp_path)
    skills_dir = tmp_path / ".agents" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "alpha").mkdir()
    (skills_dir / "beta").mkdir()

    result = CliRunner().invoke(status, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "2 local" in result.output


def test_status_no_local_skills_note(tmp_path):
    _write_marker(tmp_path)

    result = CliRunner().invoke(status, ["--workspace", str(tmp_path)])

    assert "served by hub" in result.output


# --------------------------------------------------------------------------- #
# install guards
# --------------------------------------------------------------------------- #


def test_install_non_interactive_without_harness_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(_commands, "_is_interactive", lambda: False)

    result = CliRunner().invoke(install, ["--workspace", str(tmp_path), "--no-skills"])

    assert result.exit_code != 0
    assert "Specify --harness" in result.output


def test_install_nonexistent_workspace_errors(tmp_path):
    missing = tmp_path / "does-not-exist"

    result = CliRunner().invoke(
        install, ["--workspace", str(missing), "--harness", "generic", "--no-skills"]
    )

    assert result.exit_code != 0
    assert "workspace does not exist" in result.output


# --------------------------------------------------------------------------- #
# install happy path (generic harness)
# --------------------------------------------------------------------------- #


def test_install_generic_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr(_commands, "resolve_credential", lambda: Credential("api_key"))
    # Resolve the hub URL without importing the (absent) skore package.
    monkeypatch.setattr(_commands, "resolve_hub_uri", lambda url, *a, **k: url)

    result = CliRunner().invoke(
        install,
        [
            "--workspace",
            str(tmp_path),
            "--harness",
            "generic",
            "--hub-url",
            "http://hub.test",
            "--no-skills",
        ],
    )

    assert result.exit_code == 0, result.output
    marker = json.loads((tmp_path / MARKER_FILENAME).read_text())
    assert marker["harness"] == "generic"
    assert marker["auth"] == "api_key"
    assert marker["hub_url"] == "http://hub.test"
    assert (tmp_path / "skore-agent.json").is_file()


# --------------------------------------------------------------------------- #
# _install_skills
# --------------------------------------------------------------------------- #


def test_install_skills_off_skips_subprocess(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        _commands.subprocess, "run", lambda *a, **k: called.append((a, k))
    )

    _commands._install_skills(tmp_path, install=False)

    assert called == []


def test_install_skills_on_invokes_subprocess(tmp_path, monkeypatch):
    called = []

    def fake_run(argv, **kwargs):
        called.append(argv)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(_commands.subprocess, "run", fake_run)

    _commands._install_skills(tmp_path, install=True)

    assert len(called) == 1
    assert called[0][1:] == ["-m", "skore_cli", "skills", "install", "--all"]
