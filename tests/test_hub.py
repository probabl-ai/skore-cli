"""Tests for the ``skore hub`` command group."""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from skore._plugins.hub.authentication import registry
from skore._plugins.hub.authentication.uri import URI

from skore_cli import cli

pytestmark = pytest.mark.usefixtures("monkeypatch_home", "monkeypatch_keyring")


def _invoke(args: list[str]):
    return CliRunner().invoke(cli, args)


def test_hub_no_subcommand_shows_help():
    result = _invoke(["hub"])

    assert result.exit_code == 0
    assert "api-key" in result.output


def test_hub_api_key_no_subcommand_shows_help():
    result = _invoke(["hub", "api-key"])

    assert result.exit_code == 0
    assert "add" in result.output
    assert "delete" in result.output
    assert "list" in result.output


def test_hub_api_key_add_requires_workspace():
    result = _invoke(["hub", "api-key", "add", "secret"])

    assert result.exit_code != 0
    assert "workspace" in result.output.lower()


def test_hub_api_key_add_stores_key():
    result = _invoke(
        [
            "hub",
            "api-key",
            "add",
            "secret",
            "--host=http://hub.test",
            "--workspace=team",
        ]
    )

    assert result.exit_code == 0
    assert registry.get(host="http://hub.test", workspace="team") == "secret"


def test_hub_api_key_add_without_host_uses_default_uri(monkeypatch):
    monkeypatch.delenv("SKORE_HUB_URI", raising=False)

    result = _invoke(["hub", "api-key", "add", "secret", "--workspace=team"])

    assert result.exit_code == 0
    assert registry.get(host=URI(), workspace="team") == "secret"


def test_hub_api_key_delete_requires_workspace():
    result = _invoke(["hub", "api-key", "delete"])

    assert result.exit_code != 0
    assert "workspace" in result.output.lower()


def test_hub_api_key_delete_removes_key():
    registry.set(host="http://hub.test", workspace="team", api_key="secret")

    result = _invoke(
        ["hub", "api-key", "delete", "--host=http://hub.test", "--workspace=team"]
    )

    assert result.exit_code == 0
    assert registry.get(host="http://hub.test", workspace="team") is None


def test_hub_api_key_delete_without_host_uses_environment_uri(monkeypatch):
    monkeypatch.setenv("SKORE_HUB_URI", "http://hub.test")
    registry.set(host="http://hub.test", workspace="team", api_key="secret")
    registry.set(host="http://other.test", workspace="team", api_key="other")

    result = _invoke(["hub", "api-key", "delete", "--workspace=team"])

    assert result.exit_code == 0
    assert registry.get(host="http://hub.test", workspace="team") is None
    assert registry.get(host="http://other.test", workspace="team") == "other"


def test_hub_api_key_list_empty():
    result = _invoke(["hub", "api-key", "list"])

    assert result.exit_code == 0
    assert "No API keys stored." in result.output


def test_hub_api_key_list_shows_host_and_workspace():
    registry.set(host="http://a.test", workspace="w1", api_key="k1")
    registry.set(host="http://b.test", workspace="w2", api_key="k2")

    result = _invoke(["hub", "api-key", "list"])

    assert result.exit_code == 0
    assert "http://a.test" in result.output
    assert "w1" in result.output
    assert "http://b.test" in result.output
    assert "w2" in result.output
    assert "k1" not in result.output
    assert "k2" not in result.output
