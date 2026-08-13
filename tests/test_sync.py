"""Tests for the ``skore sync`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from click.testing import CliRunner

from skore_cli.sync import _commands
from skore_cli.sync._commands import sync


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


def test_sync_reuses_one_mlflow_tracking_uri(projects):
    created, _ = projects

    result = CliRunner().invoke(
        sync,
        [
            "source",
            "--from=mlflow",
            "--from-tracking-uri=http://mlflow.test",
            "--to=mlflow",
            "--to-project=destination",
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
    ],
)
def test_sync_validates_options(args, message):
    result = CliRunner().invoke(sync, args)

    assert result.exit_code == 2
    assert message in result.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["experiment", "--from=local", "--to=local"], "same project"),
        (
            [
                "experiment",
                "--from=mlflow",
                "--from-tracking-uri=http://left",
                "--to=mlflow",
                "--to-tracking-uri=http://right",
            ],
            "same tracking URI",
        ),
    ],
)
def test_sync_rejects_invalid_endpoints_before_construction(projects, args, message):
    created, _ = projects

    result = CliRunner().invoke(sync, args)

    assert result.exit_code == 2
    assert message in result.output
    assert created == []


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
