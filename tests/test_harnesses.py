"""Tests for the harness registry, detection and config writers."""

from __future__ import annotations

import json
import tomllib
from typing import Any

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


def test_opencode_writes_session_plugin(tmp_path):
    HARNESSES["opencode"].configure(_ctx(tmp_path))
    plugin = tmp_path / ".opencode" / "plugins" / "skore-session.js"
    source = plugin.read_text()
    assert "chat.headers" in source
    assert "X-Skore-Session-Id" in source
    assert "sessionID" in source
    ignored = (tmp_path / ".gitignore").read_text().splitlines()
    assert ".opencode/plugins/skore-session.js" in ignored


def test_pi_config_matches_hub_ui(tmp_path):
    HARNESSES["pi"].configure(_ctx(tmp_path))
    config = json.loads((tmp_path / ".pi" / "agent" / "models.json").read_text())
    model = config["providers"]["skore"]["models"][0]
    assert model["id"] == "skore-agent"
    assert model["contextWindow"] == 200000
    compat = config["providers"]["skore"]["compat"]
    assert compat["sendSessionAffinityHeaders"] is True
    assert compat["sessionAffinityFormat"] == "openrouter"


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


def test_detect_copilot_by_code_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/code" if name == "code" else None,
    )
    assert _harnesses._detect_copilot(tmp_path) is True
    assert detect_harnesses(tmp_path) == ["copilot"]


def test_detect_copilot_by_code_insiders(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/code-insiders" if name == "code-insiders" else None,
    )
    assert detect_harnesses(tmp_path) == ["copilot"]


def test_copilot_config_matches_custom_endpoint(tmp_path):
    HARNESSES["copilot"].configure(_ctx(tmp_path))
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
    HARNESSES["copilot"].configure(_ctx(tmp_path))
    providers = json.loads(config_path.read_text())
    assert [entry["name"] for entry in providers] == [
        "My Other Endpoint",
        "Skore Agent",
    ]


def test_launch_copilot_prefers_code_and_opens_workspace(tmp_path, monkeypatch):
    HARNESSES["copilot"].configure(_ctx(tmp_path))
    user_root = tmp_path / "vscode-user"
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in {"code", "code-insiders"} else None,
    )
    monkeypatch.setattr(
        _harnesses,
        "_copilot_user_config_path",
        lambda binary, home=None: user_root / binary / "chatLanguageModels.json",
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)

    _harnesses.launch_harness("copilot", tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["code", str(tmp_path)]
    user_config = user_root / "code" / "chatLanguageModels.json"
    providers = json.loads(user_config.read_text())
    assert providers[-1]["name"] == "Skore Agent"
    assert providers[-1]["apiKey"] == "skore"
    assert providers[-1]["models"][0]["requestHeaders"] == {"X-API-Key": "secret-key"}


def test_launch_copilot_falls_back_to_insiders(tmp_path, monkeypatch):
    HARNESSES["copilot"].configure(_ctx(tmp_path))
    user_root = tmp_path / "vscode-user"
    captured: dict[str, list[str]] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/code-insiders" if cmd == "code-insiders" else None,
    )
    monkeypatch.setattr(
        _harnesses,
        "_copilot_user_config_path",
        lambda binary, home=None: user_root / binary / "chatLanguageModels.json",
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    _harnesses.launch_harness("copilot", tmp_path, model_id="skore-agent")
    assert captured["argv"] == ["code-insiders", str(tmp_path)]
    user_config = user_root / "code-insiders" / "chatLanguageModels.json"
    assert user_config.is_file()


def test_launch_copilot_errors_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.shutil, "which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="not installed or not on PATH"):
        _harnesses._launch_copilot(tmp_path, model_id="skore-agent")


def test_launch_copilot_errors_when_project_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    with pytest.raises(RuntimeError, match="missing .vscode/chatLanguageModels.json"):
        _harnesses._launch_copilot(tmp_path, model_id="skore-agent")


def test_launch_copilot_errors_when_project_config_unparsable(tmp_path, monkeypatch):
    config_path = tmp_path / ".vscode" / "chatLanguageModels.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{not json\n")
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    with pytest.raises(RuntimeError, match="could not parse"):
        _harnesses._launch_copilot(tmp_path, model_id="skore-agent")


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
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    monkeypatch.setattr(
        _harnesses,
        "_copilot_user_config_path",
        lambda binary, home=None: user_root / binary / "chatLanguageModels.json",
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)

    _harnesses.launch_harness("copilot", tmp_path, model_id="skore-agent")
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
    _harnesses._upsert_copilot_provider(user_config, provider)
    providers = json.loads(user_config.read_text())
    assert len(providers) == 2
    assert providers[0]["name"] == "Other"
    assert providers[1]["apiKey"] == "new-key"


def test_upsert_copilot_provider_errors_on_unparsable_file(tmp_path):
    user_config = tmp_path / "User" / "chatLanguageModels.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text("// comments are not valid JSON\n[]\n")
    with pytest.raises(RuntimeError, match="could not parse"):
        _harnesses._upsert_copilot_provider(user_config, {"name": "Skore Agent"})


def test_upsert_copilot_provider_errors_on_non_list_file(tmp_path):
    user_config = tmp_path / "User" / "chatLanguageModels.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text('{"name": "not a list"}\n')
    with pytest.raises(RuntimeError, match="could not parse"):
        _harnesses._upsert_copilot_provider(user_config, {"name": "Skore Agent"})


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
    monkeypatch.setattr(_harnesses.sys, "platform", platform)
    path = _harnesses._copilot_user_config_path("code", home=tmp_path)
    assert path == tmp_path.joinpath(*expected, "chatLanguageModels.json")
    insiders = _harnesses._copilot_user_config_path("code-insiders", home=tmp_path)
    assert "Code - Insiders" in str(insiders)


def test_copilot_user_config_path_windows_uses_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(_harnesses.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    path = _harnesses._copilot_user_config_path("code", home=tmp_path)
    assert path == tmp_path / "Roaming" / "Code" / "User" / "chatLanguageModels.json"

    monkeypatch.delenv("APPDATA")
    fallback = _harnesses._copilot_user_config_path("code", home=tmp_path)
    assert fallback == tmp_path.joinpath(
        "AppData", "Roaming", "Code", "User", "chatLanguageModels.json"
    )


def test_detect_codex_by_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda name: "/usr/bin/codex" if name == "codex" else None,
    )
    assert _harnesses._detect_codex(tmp_path) is True
    assert detect_harnesses(tmp_path) == ["codex"]


def _codex_home(tmp_path, monkeypatch):
    """Point ``Path.home`` at a scratch dir to detect any global write."""
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "home"
    monkeypatch.setattr(_harnesses.Path, "home", classmethod(lambda cls: home))
    return home


def _prepare_codex_launch(tmp_path, monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_exec(name, argv, *, env=None):
        captured["argv"] = argv
        captured["env"] = env

    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/codex" if cmd == "codex" else None,
    )
    monkeypatch.setattr(_harnesses, "_exec_harness", fake_exec)
    return captured


def _parse_config_overrides(argv: list[str]) -> dict[str, object]:
    """Parse the ``--config key=value`` tail of a codex argv as one TOML doc."""
    overrides = argv[4::2]
    assert argv[3::2] == ["--config"] * len(overrides)
    return tomllib.loads("\n".join(overrides))


def test_configure_codex_writes_project_config_only(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)

    HARNESSES["codex"].configure(_ctx(tmp_path))

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
    HARNESSES["codex"].configure(stale)
    HARNESSES["codex"].configure(_ctx(tmp_path))
    project = tomllib.loads((tmp_path / ".codex" / "skore-provider.toml").read_text())
    assert project["base_url"] == "http://hub.test/v1"
    assert project["api_key"] == "secret-key"


def test_configure_codex_escapes_toml_special_characters(tmp_path):
    api_key = 'sec"ret\\key'
    ctx = HarnessContext(workspace=tmp_path, hub_url="http://hub.test", api_key=api_key)

    HARNESSES["codex"].configure(ctx)

    project = tomllib.loads((tmp_path / ".codex" / "skore-provider.toml").read_text())
    assert project["api_key"] == api_key


def test_launch_codex_passes_provider_as_runtime_overrides(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    captured = _prepare_codex_launch(tmp_path, monkeypatch)
    HARNESSES["codex"].configure(_ctx(tmp_path))

    _harnesses.launch_harness("codex", tmp_path, model_id="skore-agent")

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

    _harnesses.launch_harness("codex", tmp_path, model_id="skore-agent")

    assert captured["argv"][:3] == ["codex", "--model", "custom-model"]


def test_launch_codex_falls_back_to_model_argument(tmp_path, monkeypatch):
    captured = _prepare_codex_launch(tmp_path, monkeypatch)
    config = tmp_path / ".codex" / "skore-provider.toml"
    config.parent.mkdir(parents=True)
    config.write_text('base_url = "http://hub.test/v1"\napi_key = "secret-key"\n')

    _harnesses.launch_harness("codex", tmp_path, model_id="fallback-model")

    assert captured["argv"][:3] == ["codex", "--model", "fallback-model"]


def test_launch_codex_errors_when_project_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/codex" if cmd == "codex" else None,
    )
    with pytest.raises(RuntimeError, match="missing .codex/skore-provider.toml"):
        _harnesses.launch_harness("codex", tmp_path)


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
        _harnesses.shutil,
        "which",
        lambda cmd: "/usr/bin/codex" if cmd == "codex" else None,
    )
    with pytest.raises(RuntimeError, match=match):
        _harnesses.launch_harness("codex", tmp_path)
