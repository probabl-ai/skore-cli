"""Tests for the ``skore sync`` command."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from click.testing import CliRunner

from skore_cli.sync import _commands
from skore_cli.sync._commands import sync

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _plain_output(output: str) -> str:
    return _ANSI_ESCAPE.sub("", output)


@dataclass
class _Project:
    name: str
    mode: str
    workspace: object | None = None
    tracking_uri: str | None = None

    def sync(self, other, *, bidirectional, dry_run):
        self.sync_args = (other, bidirectional, dry_run)
        return pd.DataFrame(
            {"key": ["report"], "direction": ["outbound"], "status": ["planned"]},
            index=pd.Index(["report-id"], name="report_id"),
        )


@pytest.fixture
def projects(monkeypatch):
    created = []
    logins = []

    def project(name, *, mode, **kwargs):
        instance = _Project(name=name, mode=mode, **kwargs)
        created.append(instance)
        return instance

    def login(*, mode):
        logins.append(mode)

    monkeypatch.setattr(_commands, "_project_api", lambda: (project, login))
    monkeypatch.setattr(_commands, "resolve_hub_uri", lambda _: "http://hub.test")
    return created, logins


def test_sync_defaults_source_to_local_and_forwards_options(projects):
    created, logins = projects

    result = CliRunner().invoke(
        sync,
        ["experiment", "--to=hub", "--to-workspace=team", "--both", "--dry-run"],
        env={"SKORE_HUB_API_KEY": "key"},
    )

    assert result.exit_code == 0, result.output
    assert [(project.name, project.mode, project.workspace) for project in created] == [
        ("experiment", "local", None),
        ("experiment", "hub", "team"),
    ]
    assert created[0].sync_args == (created[1], True, True)
    assert logins == ["hub"]
    assert "Dry run complete" in result.output


def test_sync_defaults_destination_to_local_with_custom_name(projects):
    created, _ = projects

    result = CliRunner().invoke(
        sync,
        [
            "production",
            "--from=hub",
            "--from-workspace=team",
            "--to-project=downloaded",
            "--to-workspace=~/skore",
        ],
        env={"SKORE_HUB_API_KEY": "key"},
    )

    assert result.exit_code == 0, result.output
    assert [(project.name, project.mode, project.workspace) for project in created] == [
        ("production", "hub", "team"),
        ("downloaded", "local", Path("~/skore").expanduser().resolve()),
    ]


def test_sync_uses_one_mlflow_tracking_uri(projects):
    created, _ = projects

    result = CliRunner().invoke(
        sync,
        [
            "source",
            "--from=mlflow",
            "--to=mlflow",
            "--to-project=destination",
            "--tracking-uri=http://mlflow.test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [project.tracking_uri for project in created] == [
        "http://mlflow.test",
        "http://mlflow.test",
    ]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["experiment"], "Pass --from or --to"),
        (["experiment", "--to=hub"], "--to-workspace is required for Hub"),
        (
            ["experiment", "--to=mlflow", "--to-workspace=workspace"],
            "--to-workspace is not valid for MLflow",
        ),
        (
            ["experiment", "--from=mlflow", "--to=local", "--hub-url=http://hub.test"],
            "--hub-url requires a Hub endpoint",
        ),
        (
            ["experiment", "--from=local", "--tracking-uri=http://mlflow.test"],
            "--tracking-uri requires an MLflow endpoint",
        ),
    ],
)
def test_sync_validates_options(args, message):
    result = CliRunner().invoke(sync, args)

    assert result.exit_code == 2
    assert message in _plain_output(result.output)


def test_sync_rejects_same_endpoint_before_construction(projects):
    created, _ = projects

    result = CliRunner().invoke(sync, ["experiment", "--from=local", "--to=local"])

    assert result.exit_code == 2
    assert "same project" in _plain_output(result.output)
    assert created == []


def test_sync_transfers_between_real_local_projects(tmp_path):
    from sklearn.datasets import make_regression
    from sklearn.linear_model import LinearRegression
    from skore import Project, evaluate

    source_workspace = tmp_path / "source"
    destination_workspace = tmp_path / "destination"
    X, y = make_regression(n_samples=20, n_features=2, random_state=0)
    source = Project("source", mode="local", workspace=source_workspace)
    source.put("model", evaluate(LinearRegression(), X, y, splitter=0.2))

    result = CliRunner().invoke(
        sync,
        [
            "source",
            "--from=local",
            f"--from-workspace={source_workspace}",
            "--to=local",
            "--to-project=destination",
            f"--to-workspace={destination_workspace}",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "transferred" in result.output
    destination = Project("destination", mode="local", workspace=destination_workspace)
    assert destination.summarize().frame()["key"].tolist() == ["model"]


def test_sync_requires_hub_api_key():
    result = CliRunner().invoke(
        sync,
        ["experiment", "--to=hub", "--to-workspace=team"],
    )

    assert result.exit_code != 0
    assert "SKORE_HUB_API_KEY" in result.output


def test_sync_requires_skore_with_sync(monkeypatch):
    monkeypatch.setattr(
        _commands.importlib,
        "import_module",
        lambda _: SimpleNamespace(Project=object),
    )

    result = CliRunner().invoke(sync, ["experiment", "--to=mlflow"])

    assert result.exit_code != 0
    assert "skore>=0.24.0" in result.output


def test_project_api_imports_supported_skore(monkeypatch):
    project = type("Project", (), {"sync": None})
    login = object()
    monkeypatch.setattr(
        _commands.importlib,
        "import_module",
        lambda _: SimpleNamespace(Project=project, login=login),
    )

    assert _commands._project_api() == (project, login)


def test_sync_requires_skore(monkeypatch):
    def import_skore(_):
        raise ImportError

    monkeypatch.setattr(_commands.importlib, "import_module", import_skore)

    result = CliRunner().invoke(sync, ["experiment", "--to=mlflow"])

    assert result.exit_code != 0
    assert "needs the `skore` package" in result.output


def test_sync_reports_empty_result(capsys):
    _commands._render_result(pd.DataFrame(), dry_run=False)

    assert capsys.readouterr().out == "No reports to synchronize.\n"


def test_sync_converts_backend_errors(monkeypatch):
    def project(*args, **kwargs):
        raise RuntimeError("backend error")

    monkeypatch.setattr(_commands, "_project_api", lambda: (project, None))

    result = CliRunner().invoke(sync, ["experiment", "--to=mlflow"])

    assert result.exit_code != 0
    assert "backend error" in result.output
