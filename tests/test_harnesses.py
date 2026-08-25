"""Tests for the harness registry, detection and config writers."""

from __future__ import annotations

import json
import tomllib
from typing import Any

import pytest

from skore_cli import _agents
from skore_cli._agents import (
    AGENTS,
    HarnessContext,
    installed_harnesses,
    is_harness_installed,
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
    """Keep detection off the real machine: Bob IDE is found by its bundle on
    macOS and by the ``bob-ide`` binary on other platforms."""
    monkeypatch.setattr(_agents, "BOB_IDE_APP_PATH", tmp_path / "absent.app")
    _real_which = _agents.shutil.which

    def _which(name):
        if name == "bob-ide":
            return None
        return _real_which(name)

    monkeypatch.setattr(_agents.shutil, "which", _which)


def test_opencode_installed_by_binary(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )
    assert is_harness_installed(AGENTS["opencode"]) is True
    assert [agent.harness_name for agent in installed_harnesses()] == ["opencode"]


def test_claude_installed_by_binary(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )
    assert [agent.harness_name for agent in installed_harnesses()] == ["claude"]


def test_pi_installed_by_binary(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/pi" if name == "pi" else None,
    )
    assert [agent.harness_name for agent in installed_harnesses()] == ["pi"]


def test_cursor_installed_by_binary(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/local/bin/cursor" if name == "cursor" else None,
    )
    assert is_harness_installed(AGENTS["cursor"]) is True
    assert [agent.harness_name for agent in installed_harnesses()] == ["cursor"]


def test_bob_shell_installed_by_binary(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/local/bin/bob" if name == "bob" else None,
    )
    assert is_harness_installed(AGENTS["bob"]) is True
    assert [agent.harness_name for agent in installed_harnesses()] == ["bob"]


def test_bob_ide_installed_by_app_bundle(tmp_path, monkeypatch):
    """On macOS the IDE installs no command, so detection uses the bundle."""
    monkeypatch.setattr(_agents.sys, "platform", "darwin")
    bundle = tmp_path / "IBM Bob.app"
    bundle.mkdir()
    monkeypatch.setattr(_agents, "BOB_IDE_APP_PATH", bundle)
    monkeypatch.setattr(_agents.shutil, "which", lambda name: None)
    assert is_harness_installed(AGENTS["bob-ide"]) is True
    assert [agent.harness_name for agent in installed_harnesses()] == ["bob-ide"]


def test_bob_ide_installed_by_binary_on_non_darwin(tmp_path, monkeypatch):
    """On non-macOS the IDE installs a ``bob-ide`` command on PATH."""
    monkeypatch.setattr(_agents.sys, "platform", "linux")
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/bob-ide" if name == "bob-ide" else None,
    )
    assert is_harness_installed(AGENTS["bob-ide"]) is True
    assert [agent.harness_name for agent in installed_harnesses()] == ["bob-ide"]


def test_installed_harnesses_excludes_missing(monkeypatch):
    monkeypatch.setattr(_agents.shutil, "which", lambda name: None)
    assert installed_harnesses() == []


def test_opencode_config_matches_hub_ui(tmp_path):
    AGENTS["opencode"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / "opencode.json").read_text())
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["model"] == "skore/skore-agent"
    assert config["provider"]["skore"]["name"] == "Skore Hub"
    assert config["provider"]["skore"]["models"]["skore-agent"]["name"] == "Skore Agent"


def test_opencode_writes_session_plugin(tmp_path):
    AGENTS["opencode"].configure(_ctx(tmp_path))
    plugin = tmp_path / ".opencode" / "plugins" / "skore-session.js"
    source = plugin.read_text()
    assert "chat.headers" in source
    assert "X-Skore-Session-Id" in source
    assert "sessionID" in source
    ignored = (tmp_path / ".gitignore").read_text().splitlines()
    assert ".opencode/plugins/skore-session.js" in ignored


def test_pi_config_matches_hub_ui(tmp_path):
    AGENTS["pi"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / ".pi" / "agent" / "models.json").read_text())
    model = config["providers"]["skore"]["models"][0]
    assert model["id"] == "skore-agent"
    assert model["contextWindow"] == 200000
    compat = config["providers"]["skore"]["compat"]
    assert compat["sendSessionAffinityHeaders"] is True
    assert compat["sessionAffinityFormat"] == "openrouter"


def test_cursor_config_points_at_the_mcp_endpoint(tmp_path):
    AGENTS["cursor"].configure(_ctx(tmp_path))

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
    """Bob Shell reads ``httpURL``; a plain ``url`` would mean legacy SSE."""
    AGENTS["bob"].configure(_ctx(tmp_path))

    config = json.loads((tmp_path / ".bob" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"] == {
        "httpURL": "http://hub.test/mcp",
        "headers": {"Authorization": "Bearer secret-key"},
        "alwaysAllow": ["skore_agent"],
        "disabled": False,
    }


def test_bob_ide_config_declares_the_transport_type(tmp_path):
    """Bob IDE reads the same file but wants ``type`` alongside ``url``."""
    AGENTS["bob-ide"].configure(_ctx(tmp_path))

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

    AGENTS["bob"].configure(_ctx(tmp_path))

    config = json.loads((config_dir / "mcp.json").read_text())
    assert set(config["mcpServers"]) == {"other", "skore"}
    assert config["mcpServers"]["other"] == {"command": "node"}


def test_bob_config_is_idempotent(tmp_path):
    AGENTS["bob"].configure(_ctx(tmp_path))
    AGENTS["bob"].configure(_ctx(tmp_path))

    config = json.loads((tmp_path / ".bob" / "mcp.json").read_text())
    assert config["mcpServers"]["skore"]["alwaysAllow"] == ["skore_agent"]
    assert (tmp_path / ".gitignore").read_text().count(".bob/mcp.json") == 1


def test_bob_config_refuses_to_overwrite_what_it_cannot_read(tmp_path):
    config_dir = tmp_path / ".bob"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text("{not json")

    with pytest.raises(RuntimeError, match="mcp.json"):
        AGENTS["bob"].configure(_ctx(tmp_path))

    assert (config_dir / "mcp.json").read_text() == "{not json"


@pytest.mark.parametrize(
    "name, entry",
    [
        ("opencode", "opencode.json"),
        ("claude-code", ".claude/settings.local.json"),
        ("pi", ".pi/agent/models.json"),
        ("cursor", ".cursor/mcp.json"),
        ("bob", ".bob/mcp.json"),
        ("bob-ide", ".bob/mcp.json"),
    ],
)
def test_config_embedding_the_api_key_is_gitignored(tmp_path, name, entry):
    AGENTS[name].configure(_ctx(tmp_path))

    assert "secret-key" in (tmp_path / entry).read_text()
    assert entry in (tmp_path / ".gitignore").read_text().splitlines()


def test_cursor_permissions_are_not_gitignored(tmp_path):
    """They hold no secret, and a team may well want them committed."""
    AGENTS["cursor"].configure(_ctx(tmp_path))
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

    AGENTS["cursor"].configure(_ctx(tmp_path))

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
    AGENTS["cursor"].configure(_ctx(tmp_path))
    AGENTS["cursor"].configure(_ctx(tmp_path))

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
        AGENTS["cursor"].configure(_ctx(tmp_path))

    assert (config_dir / "mcp.json").read_text() == content


def test_cursor_config_writes_nothing_when_permissions_cannot_be_read(tmp_path):
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "permissions.json").write_text("{not json")

    with pytest.raises(RuntimeError, match="permissions.json"):
        AGENTS["cursor"].configure(_ctx(tmp_path))

    assert not (config_dir / "mcp.json").exists()


def test_launch_opencode_passes_model_flag(tmp_path, monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/opencode" if cmd == "opencode" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["opencode"], tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["opencode", "-m", "skore/skore-agent"]


def test_launch_pi_passes_provider_and_model(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/pi" if cmd == "pi" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["pi"], tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["pi", "--provider", "skore", "--model", "skore-agent"]
    assert "PI_CODING_AGENT_DIR" in captured["env"]


def test_launch_cursor_opens_the_workspace(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/local/bin/cursor" if cmd == "cursor" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["cursor"], tmp_path)
    assert captured["argv"] == ["cursor", str(tmp_path)]
    # The key lives in mcp.json, so no environment has to reach the app and a
    # window opened any other way works just as well.
    assert captured["env"] is None


def test_launch_bob_shell_takes_the_workspace_from_the_cwd(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/local/bin/bob" if cmd == "bob" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["bob"], tmp_path)
    assert captured["argv"] == ["bob"]


def test_launch_bob_ide_opens_the_app_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(_agents.sys, "platform", "darwin")
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    bundle = tmp_path / "IBM Bob.app"
    bundle.mkdir()
    monkeypatch.setattr(_agents, "BOB_IDE_APP_PATH", bundle)
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["bob-ide"], tmp_path)
    assert captured["argv"] == ["open", "-a", str(bundle), str(tmp_path)]


def test_launch_bob_ide_uses_binary_on_non_darwin(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(_agents.sys, "platform", "linux")
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/bob-ide" if name == "bob-ide" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["bob-ide"], tmp_path)
    assert captured["argv"] == ["bob-ide", str(tmp_path)]


def test_launch_errors_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )
    monkeypatch.setattr(
        _agents.os,
        "execve",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        _agents.launch_harness(AGENTS["opencode"], tmp_path)


def test_claude_config_matches_hub_ui(tmp_path):
    AGENTS["claude-code"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    env = config["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://hub.test"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret-key"
    assert env["ANTHROPIC_MODEL"] == "skore-agent"


def test_launch_claude_loads_settings_env(tmp_path, monkeypatch):
    AGENTS["claude-code"].configure(_ctx(tmp_path))
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/claude" if cmd == "claude" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["claude-code"], tmp_path, model_id="skore-agent")

    assert captured["argv"] == ["claude"]
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret-key"


def test_launch_claude_without_settings_uses_process_env(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_exec(name, argv, *, env=None):
        captured["env"] = env

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/claude" if cmd == "claude" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["claude-code"], tmp_path)

    assert "ANTHROPIC_AUTH_TOKEN" not in captured["env"]


def test_launch_harness_errors_when_not_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(_agents.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _agents.launch_harness(AGENTS["opencode"], tmp_path)


def test_exec_harness_errors_when_executable_missing(monkeypatch):
    monkeypatch.setattr(_agents.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _agents._exec_harness("opencode", ["opencode"])


def test_exec_harness_invokes_execve(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(_agents.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    def fake_execve(executable, argv, env):
        recorded["executable"] = executable
        recorded["argv"] = argv
        recorded["env"] = env

    monkeypatch.setattr(_agents.os, "execve", fake_execve)
    _agents._exec_harness("opencode", ["opencode", "-m", "x"], env={"A": "B"})

    assert recorded["executable"] == "/usr/bin/opencode"
    assert recorded["argv"] == ["opencode", "-m", "x"]
    assert recorded["env"] == {"A": "B"}


def test_detect_copilot_by_code_binary(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/code" if name == "code" else None,
    )
    assert is_harness_installed(AGENTS["github-copilot"]) is True
    assert [agent.harness_name for agent in installed_harnesses()] == ["copilot"]


def test_detect_copilot_by_code_insiders(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/code-insiders" if name == "code-insiders" else None,
    )
    assert [agent.harness_name for agent in installed_harnesses()] == ["copilot"]


def test_copilot_config_matches_custom_endpoint(tmp_path):
    AGENTS["github-copilot"].configure(_ctx(tmp_path))
    config_path = tmp_path / ".vscode" / "chatLanguageModels.json"
    providers = json.loads(config_path.read_text())
    assert len(providers) == 1
    provider = providers[0]
    assert provider["name"] == "Skore Agent"
    assert provider["vendor"] == "customendpoint"
    assert provider["apiKey"] == "skore"
    assert provider["apiType"] == "chat-completions"
    model = provider["models"][0]
    assert model["id"] == "skore-agent"
    assert model["url"] == "http://hub.test/v1/chat/completions"
    assert model["toolCalling"] is True
    assert model["vision"] is False
    assert model["maxInputTokens"] == 200000
    assert model["maxOutputTokens"] == 8192
    assert model["requestHeaders"] == {"X-API-Key": "secret-key"}
    gitignore = (tmp_path / ".gitignore").read_text().splitlines()
    assert ".vscode/chatLanguageModels.json" in gitignore


def test_configure_copilot_preserves_other_entries(tmp_path):
    config_path = tmp_path / ".vscode" / "chatLanguageModels.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            [{"name": "My Other Endpoint", "vendor": "customendpoint", "models": []}]
        )
        + "\n"
    )
    AGENTS["github-copilot"].configure(_ctx(tmp_path))
    providers = json.loads(config_path.read_text())
    assert [entry["name"] for entry in providers] == [
        "My Other Endpoint",
        "Skore Agent",
    ]


def test_launch_copilot_prefers_code_and_opens_workspace(tmp_path, monkeypatch):
    AGENTS["github-copilot"].configure(_ctx(tmp_path))
    user_root = tmp_path / "vscode-user"
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in {"code", "code-insiders"} else None,
    )
    monkeypatch.setattr(
        _agents,
        "_copilot_user_config_path",
        lambda binary, home=None: user_root / binary / "chatLanguageModels.json",
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)

    _agents.launch_harness(AGENTS["github-copilot"], tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["code", str(tmp_path)]
    user_config = user_root / "code" / "chatLanguageModels.json"
    providers = json.loads(user_config.read_text())
    assert providers[-1]["name"] == "Skore Agent"
    assert providers[-1]["apiKey"] == "skore"
    assert providers[-1]["models"][0]["requestHeaders"] == {"X-API-Key": "secret-key"}


def test_launch_copilot_falls_back_to_insiders(tmp_path, monkeypatch):
    AGENTS["github-copilot"].configure(_ctx(tmp_path))
    user_root = tmp_path / "vscode-user"
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/code-insiders" if cmd == "code-insiders" else None,
    )
    monkeypatch.setattr(
        _agents,
        "_copilot_user_config_path",
        lambda binary, home=None: user_root / binary / "chatLanguageModels.json",
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    _agents.launch_harness(AGENTS["github-copilot"], tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["code-insiders", str(tmp_path)]
    user_config = user_root / "code-insiders" / "chatLanguageModels.json"
    assert user_config.is_file()


def test_launch_copilot_errors_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(_agents.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _agents._launch_copilot(tmp_path, "skore-agent")


def test_launch_copilot_errors_when_project_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    with pytest.raises(RuntimeError, match="missing .vscode/chatLanguageModels.json"):
        _agents._launch_copilot(tmp_path, "skore-agent")


def test_launch_copilot_errors_when_project_config_unparsable(tmp_path, monkeypatch):
    config_path = tmp_path / ".vscode" / "chatLanguageModels.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{not json\n")
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    with pytest.raises(RuntimeError, match="could not parse"):
        _agents._launch_copilot(tmp_path, "skore-agent")


def test_launch_copilot_finds_provider_among_others(tmp_path, monkeypatch):
    config_path = tmp_path / ".vscode" / "chatLanguageModels.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            [
                {"name": "My Other Endpoint", "vendor": "customendpoint", "models": []},
                {
                    "name": "Skore Agent",
                    "vendor": "customendpoint",
                    "apiKey": "skore",
                    "models": [
                        {
                            "id": "skore-agent",
                            "requestHeaders": {"X-API-Key": "secret-key"},
                        }
                    ],
                },
            ]
        )
        + "\n"
    )
    user_root = tmp_path / "vscode-user"
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    monkeypatch.setattr(
        _agents,
        "_copilot_user_config_path",
        lambda binary, home=None: user_root / binary / "chatLanguageModels.json",
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)

    _agents.launch_harness(AGENTS["github-copilot"], tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["code", str(tmp_path)]
    user_config = user_root / "code" / "chatLanguageModels.json"
    providers = json.loads(user_config.read_text())
    assert providers[-1]["name"] == "Skore Agent"
    assert providers[-1]["models"][0]["requestHeaders"] == {"X-API-Key": "secret-key"}


def test_upsert_copilot_provider_preserves_other_entries(tmp_path):
    user_config = tmp_path / "User" / "chatLanguageModels.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        json.dumps(
            [
                {"name": "Other", "vendor": "openai", "models": []},
                {
                    "name": "Skore Agent",
                    "vendor": "customendpoint",
                    "apiKey": "old-key",
                    "models": [],
                },
            ]
        )
        + "\n"
    )
    provider = {
        "name": "Skore Agent",
        "vendor": "customendpoint",
        "apiKey": "new-key",
        "apiType": "chat-completions",
        "models": [{"id": "skore-agent", "name": "Skore Agent"}],
    }
    _agents._upsert_copilot_provider(user_config, provider)
    providers = json.loads(user_config.read_text())
    assert len(providers) == 2
    assert providers[0]["name"] == "Other"
    assert providers[1]["apiKey"] == "new-key"


def test_upsert_copilot_provider_errors_on_unparsable_file(tmp_path):
    user_config = tmp_path / "User" / "chatLanguageModels.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text("// comments are not valid JSON\n[]\n")
    with pytest.raises(RuntimeError, match="could not parse"):
        _agents._upsert_copilot_provider(user_config, {"name": "Skore Agent"})


def test_upsert_copilot_provider_errors_on_non_list_file(tmp_path):
    user_config = tmp_path / "User" / "chatLanguageModels.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text('{"name": "not a list"}\n')
    with pytest.raises(RuntimeError, match="could not parse"):
        _agents._upsert_copilot_provider(user_config, {"name": "Skore Agent"})


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", ("Library", "Application Support", "Code", "User")),
        ("linux", (".config", "Code", "User")),
    ],
)
def test_copilot_user_config_path_per_platform(
    tmp_path, monkeypatch, platform, expected
):
    monkeypatch.setattr(_agents.sys, "platform", platform)
    path = _agents._copilot_user_config_path("code", home=tmp_path)
    assert path == tmp_path.joinpath(*expected, "chatLanguageModels.json")
    insiders = _agents._copilot_user_config_path("code-insiders", home=tmp_path)
    assert "Code - Insiders" in str(insiders)


def test_copilot_user_config_path_windows_uses_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(_agents.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    path = _agents._copilot_user_config_path("code", home=tmp_path)
    assert path == tmp_path / "Roaming" / "Code" / "User" / "chatLanguageModels.json"

    monkeypatch.delenv("APPDATA")
    fallback = _agents._copilot_user_config_path("code", home=tmp_path)
    assert fallback == tmp_path.joinpath(
        "AppData", "Roaming", "Code", "User", "chatLanguageModels.json"
    )


def test_detect_codex_by_binary(monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda name: "/usr/bin/codex" if name == "codex" else None,
    )
    assert is_harness_installed(AGENTS["codex"]) is True
    assert [agent.harness_name for agent in installed_harnesses()] == ["codex"]


def _codex_home(tmp_path, monkeypatch):
    """Point ``Path.home`` at a scratch dir to detect any global write."""
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "home"
    monkeypatch.setattr(_agents.Path, "home", classmethod(lambda cls: home))
    return home


def _prepare_codex_launch(tmp_path, monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/codex" if cmd == "codex" else None,
    )
    monkeypatch.setattr(_agents, "_exec_harness", fake_exec)
    return captured


def _parse_config_overrides(argv: list[str]) -> dict[str, object]:
    """Parse the ``--config key=value`` tail of a codex argv as one TOML doc."""
    overrides = argv[4::2]
    assert argv[3::2] == ["--config"] * len(overrides)
    return tomllib.loads("\n".join(overrides))


def test_configure_codex_writes_project_config_only(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)

    AGENTS["codex"].configure(_ctx(tmp_path))

    project = tomllib.loads((tmp_path / ".codex" / "skore-provider.toml").read_text())
    assert project["model"] == "skore-agent"
    assert project["model_provider"] == "skore"
    assert project["base_url"] == "http://hub.test/v1"
    assert project["api_key"] == "secret-key"
    gitignore = (tmp_path / ".gitignore").read_text().splitlines()
    assert ".codex/skore-provider.toml" in gitignore
    assert not home.exists()


def test_configure_codex_overwrites_previous_project_config(tmp_path):
    stale = HarnessContext(
        workspace=tmp_path, hub_url="http://old.test", api_key="old-key"
    )
    AGENTS["codex"].configure(stale)
    AGENTS["codex"].configure(_ctx(tmp_path))
    project = tomllib.loads((tmp_path / ".codex" / "skore-provider.toml").read_text())
    assert project["base_url"] == "http://hub.test/v1"
    assert project["api_key"] == "secret-key"


def test_configure_codex_escapes_toml_special_characters(tmp_path):
    api_key = 'sec"ret\\key'
    ctx = HarnessContext(workspace=tmp_path, hub_url="http://hub.test", api_key=api_key)

    AGENTS["codex"].configure(ctx)

    project = tomllib.loads((tmp_path / ".codex" / "skore-provider.toml").read_text())
    assert project["api_key"] == api_key


def test_launch_codex_passes_provider_as_runtime_overrides(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    captured = _prepare_codex_launch(tmp_path, monkeypatch)
    AGENTS["codex"].configure(_ctx(tmp_path))

    _agents.launch_harness(AGENTS["codex"], tmp_path, model_id="skore-agent")

    argv = captured["argv"]
    assert argv[:3] == ["codex", "--model", "skore-agent"]
    data = _parse_config_overrides(argv)
    assert data["model_provider"] == "skore"
    provider = data["model_providers"]["skore"]
    assert provider["name"] == "Skore Agent"
    assert provider["base_url"] == "http://hub.test/v1"
    assert provider["wire_api"] == "responses"
    assert provider["env_http_headers"] == {"X-API-Key": "SKORE_AGENT_API_KEY"}
    assert "http_headers" not in provider
    assert "env_key" not in provider
    assert "secret-key" not in argv  # the key never rides the command line
    assert captured["env"]["SKORE_AGENT_API_KEY"] == "secret-key"
    assert not home.exists()


def test_launch_codex_prefers_project_model(tmp_path, monkeypatch):
    captured = _prepare_codex_launch(tmp_path, monkeypatch)
    config = tmp_path / ".codex" / "skore-provider.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        'model = "custom-model"\n'
        'model_provider = "skore"\n'
        'base_url = "http://hub.test/v1"\n'
        'api_key = "secret-key"\n'
    )

    _agents.launch_harness(AGENTS["codex"], tmp_path, model_id="skore-agent")

    assert captured["argv"][:3] == ["codex", "--model", "custom-model"]


def test_launch_codex_falls_back_to_model_argument(tmp_path, monkeypatch):
    captured = _prepare_codex_launch(tmp_path, monkeypatch)
    config = tmp_path / ".codex" / "skore-provider.toml"
    config.parent.mkdir(parents=True)
    config.write_text('base_url = "http://hub.test/v1"\napi_key = "secret-key"\n')

    _agents.launch_harness(AGENTS["codex"], tmp_path, model_id="fallback-model")

    assert captured["argv"][:3] == ["codex", "--model", "fallback-model"]


def test_launch_codex_errors_when_project_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/codex" if cmd == "codex" else None,
    )
    with pytest.raises(RuntimeError, match="missing .codex/skore-provider.toml"):
        _agents.launch_harness(AGENTS["codex"], tmp_path)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (
            'model = "skore-agent"\nmodel_provider = "skore"\napi_key = "secret-key"\n',
            "missing a valid base_url",
        ),
        (
            'model = "skore-agent"\n'
            'model_provider = "skore"\n'
            'base_url = ""\n'
            'api_key = "secret-key"\n',
            "missing a valid base_url",
        ),
        (
            'model = "skore-agent"\n'
            'model_provider = "skore"\n'
            'base_url = "http://hub.test/v1"\n',
            "missing a valid api_key",
        ),
        (
            'model = "skore-agent"\n'
            'model_provider = "skore"\n'
            'base_url = "http://hub.test/v1"\n'
            'api_key = ""\n',
            "missing a valid api_key",
        ),
        ("model = [unterminated\n", "could not parse"),
    ],
)
def test_launch_codex_errors_when_project_config_invalid(
    tmp_path, monkeypatch, payload, match
):
    config = tmp_path / ".codex" / "skore-provider.toml"
    config.parent.mkdir(parents=True)
    config.write_text(payload)
    monkeypatch.setattr(
        _agents.shutil,
        "which",
        lambda cmd: "/usr/bin/codex" if cmd == "codex" else None,
    )
    with pytest.raises(RuntimeError, match=match):
        _agents.launch_harness(AGENTS["codex"], tmp_path)
