"""Tests for the harness registry, detection and config writers."""

from __future__ import annotations

import json

import pytest

from skore_cli.agent import _harnesses
from skore_cli.agent._harnesses import (
    HARNESSES,
    HarnessContext,
    detect_harnesses,
)


def _ctx(workspace, **kwargs):
    return HarnessContext(
        workspace=workspace,
        hub_url="http://hub.test",
        api_key="secret-key",
        **kwargs,
    )


@pytest.fixture(autouse=True)
def no_bob_ide_app(tmp_path, monkeypatch):
    """Keep detection off the real machine: Bob IDE is found by its bundle."""
    monkeypatch.setattr(_harnesses, "BOB_IDE_APP_PATH", tmp_path / "absent.app")


def test_detect_opencode_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )
    assert _harnesses._detect_opencode(tmp_path) is True
    assert detect_harnesses(tmp_path) == ["opencode"]


def test_detect_claude_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )
    assert detect_harnesses(tmp_path) == ["claude"]


def test_detect_pi_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/pi" if name == "pi" else None,
    )
    assert detect_harnesses(tmp_path) == ["pi"]


def test_detect_cursor_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/local/bin/cursor" if name == "cursor" else None,
    )
    assert detect_harnesses(tmp_path) == ["cursor"]


def test_detect_cursor_ignores_an_install_without_the_cli(tmp_path, monkeypatch):
    """Offering a harness `_exec_harness` cannot start only fails later, louder."""
    monkeypatch.setattr(_harnesses.shutil, "which", lambda name: None)
    assert _harnesses._detect_cursor(tmp_path) is False


def test_detect_bob_shell_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/local/bin/bob" if name == "bob" else None,
    )
    assert detect_harnesses(tmp_path) == ["bob"]


def test_detect_bob_ide_by_app_bundle(tmp_path, monkeypatch):
    """The IDE installs no command, so `_launch_bob_ide` opens the bundle."""
    bundle = tmp_path / "IBM Bob.app"
    bundle.mkdir()
    monkeypatch.setattr(_harnesses, "BOB_IDE_APP_PATH", bundle)
    monkeypatch.setattr(_harnesses.shutil, "which", lambda name: None)
    assert detect_harnesses(tmp_path) == ["bob-ide"]


def test_detect_harnesses_excludes_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda name: None)
    assert detect_harnesses(tmp_path) == []


def test_opencode_config_matches_hub_ui(tmp_path):
    HARNESSES["opencode"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / "opencode.json").read_text())
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["model"] == "skore/skore-agent"
    assert config["provider"]["skore"]["name"] == "Skore Hub"
    assert config["provider"]["skore"]["models"]["skore-agent"]["name"] == "Skore Agent"


def test_pi_config_matches_hub_ui(tmp_path):
    HARNESSES["pi"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / ".pi" / "agent" / "models.json").read_text())
    model = config["providers"]["skore"]["models"][0]
    assert model["id"] == "skore-agent"
    assert model["contextWindow"] == 200000


def test_cursor_config_points_at_the_mcp_endpoint(tmp_path):
    HARNESSES["cursor"].configure(_ctx(tmp_path))

    config = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"] == {
        "url": "http://hub.test/mcp",
        "headers": {"Authorization": "Bearer secret-key"},
    }

    permissions = json.loads((tmp_path / ".cursor" / "permissions.json").read_text())
    assert permissions["mcpAllowlist"] == ["skore:*"]
    assert permissions["autoRun"]["allow_instructions"] == [
        "curl fetching a Skore materialize URL under /v1/materialize/ to write "
        "a template or script into the workspace",
        "calls to the skore MCP server's skore_agent tool",
    ]


def test_bob_shell_config_declares_the_streamable_http_url(tmp_path):
    """Bob Shell reads `httpURL`; a plain `url` would mean legacy SSE."""
    HARNESSES["bob"].configure(_ctx(tmp_path))

    config = json.loads((tmp_path / ".bob" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"] == {
        "httpURL": "http://hub.test/mcp",
        "headers": {"Authorization": "Bearer secret-key"},
        "alwaysAllow": ["skore_agent"],
        "disabled": False,
    }


def test_bob_ide_config_declares_the_transport_type(tmp_path):
    """Bob IDE reads the same file but wants `type` alongside `url`."""
    HARNESSES["bob-ide"].configure(_ctx(tmp_path))

    config = json.loads((tmp_path / ".bob" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"] == {
        "type": "streamable-http",
        "url": "http://hub.test/mcp",
        "headers": {"Authorization": "Bearer secret-key"},
        "alwaysAllow": ["skore_agent"],
        "disabled": False,
    }


def test_bob_config_preserves_what_the_user_already_had(tmp_path):
    config_dir = tmp_path / ".bob"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "node"}}})
    )

    HARNESSES["bob"].configure(_ctx(tmp_path))

    config = json.loads((config_dir / "mcp.json").read_text())
    assert set(config["mcpServers"]) == {"other", "skore"}
    assert config["mcpServers"]["other"] == {"command": "node"}


def test_bob_config_is_idempotent(tmp_path):
    HARNESSES["bob"].configure(_ctx(tmp_path))
    HARNESSES["bob"].configure(_ctx(tmp_path))

    config = json.loads((tmp_path / ".bob" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"]["alwaysAllow"] == ["skore_agent"]
    assert (tmp_path / ".gitignore").read_text().count(".bob/mcp.json") == 1


def test_bob_config_refuses_to_overwrite_what_it_cannot_read(tmp_path):
    config_dir = tmp_path / ".bob"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text("{not json")

    with pytest.raises(RuntimeError, match="mcp.json"):
        HARNESSES["bob"].configure(_ctx(tmp_path))

    assert (config_dir / "mcp.json").read_text() == "{not json"


@pytest.mark.parametrize(
    "name, entry",
    [
        ("opencode", "opencode.json"),
        ("claude", ".claude/settings.local.json"),
        ("pi", ".pi/agent/models.json"),
        ("cursor", ".cursor/mcp.json"),
        ("bob", ".bob/mcp.json"),
        ("bob-ide", ".bob/mcp.json"),
    ],
)
def test_config_embedding_the_api_key_is_gitignored(tmp_path, name, entry):
    HARNESSES[name].configure(_ctx(tmp_path))

    assert "secret-key" in (tmp_path / entry).read_text()
    assert entry in (tmp_path / ".gitignore").read_text().splitlines()


def test_cursor_permissions_are_not_gitignored(tmp_path):
    """They hold no secret, and a team may well want them committed."""
    HARNESSES["cursor"].configure(_ctx(tmp_path))
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "permissions.json" not in gitignore


def test_cursor_config_preserves_what_the_user_already_had(tmp_path):
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"url": "http://elsewhere"}}})
    )
    (config_dir / "permissions.json").write_text(
        json.dumps(
            {
                "mcpAllowlist": ["other:*"],
                "allow": ["Read(**)"],
                "autoRun": {"allow_instructions": ["anything the user allowed"]},
            }
        )
    )

    HARNESSES["cursor"].configure(_ctx(tmp_path))

    config = json.loads((config_dir / "mcp.json").read_text())
    assert set(config["mcpServers"]) == {"other", "skore"}
    assert config["mcpServers"]["other"] == {"url": "http://elsewhere"}

    permissions = json.loads((config_dir / "permissions.json").read_text())
    assert permissions["mcpAllowlist"] == ["other:*", "skore:*"]
    assert permissions["allow"] == ["Read(**)"]
    assert permissions["autoRun"]["allow_instructions"][0] == (
        "anything the user allowed"
    )
    assert len(permissions["autoRun"]["allow_instructions"]) == 3


def test_cursor_config_is_idempotent(tmp_path):
    HARNESSES["cursor"].configure(_ctx(tmp_path))
    HARNESSES["cursor"].configure(_ctx(tmp_path))

    permissions = json.loads((tmp_path / ".cursor" / "permissions.json").read_text())
    assert permissions["mcpAllowlist"] == ["skore:*"]
    assert len(permissions["autoRun"]["allow_instructions"]) == 2


@pytest.mark.parametrize("content", ["{not json", "// a comment\n{}", "[]"])
def test_cursor_config_refuses_to_overwrite_what_it_cannot_read(tmp_path, content):
    """Cursor accepts comments in these files; wiping one would lose real config."""
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(content)

    with pytest.raises(RuntimeError, match="mcp.json"):
        HARNESSES["cursor"].configure(_ctx(tmp_path))

    assert (config_dir / "mcp.json").read_text() == content


def test_cursor_config_writes_nothing_when_permissions_cannot_be_read(tmp_path):
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "permissions.json").write_text("{not json")

    with pytest.raises(RuntimeError, match="permissions.json"):
        HARNESSES["cursor"].configure(_ctx(tmp_path))

    assert not (config_dir / "mcp.json").exists()


def test_launch_opencode_passes_model_flag(tmp_path, monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/opencode" if cmd == "opencode" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("opencode", tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["opencode", "-m", "skore/skore-agent"]


def test_launch_pi_passes_provider_and_model(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/pi" if cmd == "pi" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("pi", tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["pi", "--provider", "skore", "--model", "skore-agent"]
    assert "PI_CODING_AGENT_DIR" in captured["env"]


def test_launch_cursor_opens_the_workspace(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/local/bin/cursor" if cmd == "cursor" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("cursor", tmp_path)
    assert captured["argv"] == ["cursor", str(tmp_path)]
    # The key lives in mcp.json, so no environment has to reach the app and a
    # window opened any other way works just as well.
    assert captured["env"] is None


def test_launch_bob_shell_takes_the_workspace_from_the_cwd(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/local/bin/bob" if cmd == "bob" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("bob", tmp_path)
    assert captured["argv"] == ["bob"]


def test_launch_bob_ide_opens_the_app_bundle(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    bundle = tmp_path / "IBM Bob.app"
    bundle.mkdir()
    monkeypatch.setattr(_harnesses, "BOB_IDE_APP_PATH", bundle)
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("bob-ide", tmp_path)
    assert captured["argv"] == ["open", "-a", str(bundle), str(tmp_path)]


def test_launch_errors_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )
    monkeypatch.setattr(
        _harnesses.os,
        "execve",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        _harnesses.launch_harness("opencode", tmp_path)


def test_claude_config_matches_hub_ui(tmp_path):
    HARNESSES["claude"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    env = config["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://hub.test"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret-key"
    assert env["ANTHROPIC_MODEL"] == "skore-agent"


def test_launch_claude_loads_settings_env(tmp_path, monkeypatch):
    HARNESSES["claude"].configure(_ctx(tmp_path))
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/claude" if cmd == "claude" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("claude", tmp_path, model_id="skore-agent")

    assert captured["argv"] == ["claude"]
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret-key"


def test_launch_claude_without_settings_uses_process_env(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/claude" if cmd == "claude" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("claude", tmp_path)

    assert "ANTHROPIC_AUTH_TOKEN" not in captured["env"]


def test_launch_harness_errors_when_not_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _harnesses.launch_harness("opencode", tmp_path)


def test_exec_harness_errors_when_executable_missing(monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _harnesses._exec_harness("opencode", ["opencode"])


def test_exec_harness_invokes_execve(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(_harnesses.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    def fake_execve(executable, argv, env):
        recorded["executable"] = executable
        recorded["argv"] = argv
        recorded["env"] = env

    monkeypatch.setattr(_harnesses.os, "execve", fake_execve)
    _harnesses._exec_harness("opencode", ["opencode", "-m", "x"], env={"A": "B"})

    assert recorded["executable"] == "/usr/bin/opencode"
    assert recorded["argv"] == ["opencode", "-m", "x"]
    assert recorded["env"] == {"A": "B"}
