"""Unified agent registry, runtime detection, skills, and harness behavior."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_AGENT = "agents"
DEFAULT_MODEL_ID = "skore-agent"
# Name under which Skore registers in each harness config (model provider or
# MCP server).
SKORE_PROVIDER_KEY = "skore"

# OpenCode
OPENCODE_SCHEMA = "https://opencode.ai/config.json"
OPENCODE_SESSION_PLUGIN = ".opencode/plugins/skore-session.js"
OPENCODE_SESSION_PLUGIN_SOURCE = """\
export const SkoreSessionPlugin = async () => ({
  "chat.headers": async (input, output) => {
    if (input.sessionID) {
      output.headers["X-Skore-Session-Id"] = input.sessionID;
    }
  },
});
"""

# Cursor
# Cursor concatenates the per-user and per-workspace allowlists, so this entry
# applies on top of whatever the user already allows. A convenience, not a
# security boundary.
CURSOR_ALLOWLIST_ENTRY = "skore:*"
CURSOR_AUTORUN_INSTRUCTIONS = (
    "curl fetching a Skore materialize URL under /v1/materialize/ to write a "
    "template or script into the workspace",
    "calls to the skore MCP server's skore_agent tool",
)

# Bob
# On macOS, Bob IDE ships as an application bundle with no command on PATH.
# On Windows it installs a ``bob-ide`` command; on Linux the .deb/.rpm package
# does the same. The macOS bundle path is a module constant so tests can point
# it somewhere that does not exist.
BOB_IDE_APP_PATH = Path("/Applications/IBM Bob.app")

# GitHub Copilot
COPILOT_PROVIDER_NAME = "Skore Agent"
COPILOT_PROJECT_CONFIG = ".vscode/chatLanguageModels.json"
COPILOT_BINARIES = ("code", "code-insiders")
CODEX_PROVIDER_KEY = "skore"
CODEX_PROVIDER_NAME = "Skore Agent"
CODEX_PROJECT_CONFIG = ".codex/skore-provider.toml"
CODEX_API_KEY_ENV = "SKORE_AGENT_API_KEY"
SDK_API_KEY_ENV = "SKORE_HUB_API_KEY"
SDK_URI_ENV = "SKORE_HUB_URI"


@dataclass(frozen=True)
class HarnessContext:
    """Inputs shared by every harness configuration writer."""

    workspace: Path
    hub_url: str
    api_key: str
    model_id: str = DEFAULT_MODEL_ID

    @property
    def base_url(self) -> str:
        """Return the OpenAI-compatible API base URL."""
        return f"{self.hub_url.rstrip('/')}/v1"

    @property
    def mcp_url(self) -> str:
        return f"{self.hub_url.rstrip('/')}/mcp"


Configure = Callable[[HarnessContext], dict[str, Any]]
Launch = Callable[[Path, str], None]


@dataclass(frozen=True)
class Agent:
    """An agent and its optional detection, skills, and harness capabilities."""

    name: str
    label: str
    env_var: str | None = None
    detection_priority: int | None = None
    skill_target: str | None = None
    user_skills_dir: str | None = None
    project_skills_dir: str | None = None
    harness_name: str | None = None
    harness_label: str | None = None
    harness_binaries: tuple[str, ...] = ()
    configure: Configure | None = None
    launch: Launch | None = None

    @property
    def harness_display_name(self) -> str:
        """Return the harness label shown to users."""
        return self.harness_label or self.label


def _configure_opencode(ctx: HarnessContext) -> dict[str, Any]:
    """Write ``opencode.json`` with the Skore Hub provider."""
    from skore_cli._style import console
    from skore_cli.agent._skore_file import ensure_gitignore_entry

    config_path = ctx.workspace / "opencode.json"
    config: dict[str, Any] = {
        "$schema": OPENCODE_SCHEMA,
        "model": f"{SKORE_PROVIDER_KEY}/{ctx.model_id}",
        "provider": {
            SKORE_PROVIDER_KEY: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Skore Hub",
                "options": {
                    "baseURL": ctx.base_url,
                    "apiKey": ctx.api_key,
                },
                "models": {ctx.model_id: {"name": "Skore Agent"}},
            }
        },
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    ensure_gitignore_entry(ctx.workspace, "opencode.json")
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")

    plugin_path = ctx.workspace / OPENCODE_SESSION_PLUGIN
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_path.write_text(OPENCODE_SESSION_PLUGIN_SOURCE)
    ensure_gitignore_entry(ctx.workspace, OPENCODE_SESSION_PLUGIN)
    console.print(f"[skore.ok]+[/] wrote [skore.path]{plugin_path}[/]")
    return {"config_path": str(config_path), "plugin_path": str(plugin_path)}


def _configure_claude(ctx: HarnessContext) -> dict[str, Any]:
    """Write ``.claude/settings.local.json`` for Claude."""
    from skore_cli._style import console
    from skore_cli.agent._skore_file import ensure_gitignore_entry

    config_dir = ctx.workspace / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "settings.local.json"
    payload = {
        "env": {
            "ANTHROPIC_BASE_URL": ctx.hub_url.rstrip("/"),
            "ANTHROPIC_AUTH_TOKEN": ctx.api_key,
            "ANTHROPIC_MODEL": ctx.model_id,
        }
    }
    config_path.write_text(json.dumps(payload, indent=2) + "\n")
    ensure_gitignore_entry(ctx.workspace, ".claude/settings.local.json")
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    return {"config_path": str(config_path)}


def _configure_pi(ctx: HarnessContext) -> dict[str, Any]:
    """Write ``.pi/agent/models.json`` for Pi."""
    from skore_cli._style import console
    from skore_cli.agent._skore_file import ensure_gitignore_entry

    config_dir = ctx.workspace / ".pi" / "agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "models.json"
    payload = {
        "providers": {
            SKORE_PROVIDER_KEY: {
                "baseUrl": ctx.base_url,
                "api": "openai-completions",
                "apiKey": ctx.api_key,
                "authHeader": True,
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                    "sendSessionAffinityHeaders": True,
                    "sessionAffinityFormat": "openrouter",
                },
                "models": [
                    {
                        "id": ctx.model_id,
                        "name": "Skore Agent",
                        "reasoning": True,
                        "input": ["text"],
                        "contextWindow": 200000,
                        "maxTokens": 8192,
                    }
                ],
            }
        }
    }
    config_path.write_text(json.dumps(payload, indent=2) + "\n")
    ensure_gitignore_entry(ctx.workspace, ".pi/agent/models.json")
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    return {"config_path": str(config_path)}


def _load_json_object(path: Path) -> dict[str, Any]:
    """Return the JSON object stored at ``path``, or an empty one when absent.

    Refuses anything else: the caller writes the result back, so treating an
    unreadable file as empty would drop the servers and rules it holds. Cursor
    accepts comments in these files and Python's parser does not.
    """
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"{path} is not valid JSON (comments are not supported here); "
            "fix or move it, then run `skore agent` again."
        ) from error
    if not isinstance(data, dict):
        raise RuntimeError(
            f"{path} does not hold a JSON object; fix or move it, then run "
            "`skore agent` again."
        )
    return data


def _configure_cursor(ctx: HarnessContext) -> dict[str, Any]:
    """Point Cursor's MCP client at the hub and pre-approve the Skore tools.

    These two files belong to Cursor, not to Skore, so they are read-modify-
    written: another MCP server or permission rule the user set up survives.
    """
    from skore_cli._style import console
    from skore_cli.agent._skore_file import ensure_gitignore_entry

    config_dir = ctx.workspace / ".cursor"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / "mcp.json"
    permissions_path = config_dir / "permissions.json"
    # Both files are read up front so an unreadable second one cannot leave the
    # workspace half-configured.
    config = _load_json_object(config_path)
    permissions = _load_json_object(permissions_path)

    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[SKORE_PROVIDER_KEY] = {
        # Without an explicit transport Cursor probes streamable HTTP and, on
        # any failure, retries the same URL as legacy SSE, which the hub does
        # not serve: the real error is then buried under an SSE 404.
        "type": "http",
        "url": ctx.mcp_url,
        # Written out rather than interpolated from the environment: Cursor
        # resolves ${env:...} against its own process, which is whatever
        # launched the app, not `skore agent`.
        "headers": {"Authorization": f"Bearer {ctx.api_key}"},
    }
    config["mcpServers"] = servers
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    ensure_gitignore_entry(ctx.workspace, ".cursor/mcp.json")

    allowlist = permissions.get("mcpAllowlist")
    if not isinstance(allowlist, list):
        allowlist = []
    if CURSOR_ALLOWLIST_ENTRY not in allowlist:
        allowlist.append(CURSOR_ALLOWLIST_ENTRY)
    permissions["mcpAllowlist"] = allowlist
    auto_run = permissions.get("autoRun")
    if not isinstance(auto_run, dict):
        auto_run = {}
    instructions = auto_run.get("allow_instructions")
    if not isinstance(instructions, list):
        instructions = []
    for instruction in CURSOR_AUTORUN_INSTRUCTIONS:
        if instruction not in instructions:
            instructions.append(instruction)
    auto_run["allow_instructions"] = instructions
    permissions["autoRun"] = auto_run
    permissions_path.write_text(json.dumps(permissions, indent=2) + "\n")

    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    console.print(f"[skore.ok]+[/] wrote [skore.path]{permissions_path}[/]")
    console.print(
        f"[skore.muted]  turn [skore.skill]{SKORE_PROVIDER_KEY}[/] on under "
        f"Settings -> Tools & MCP; Cursor asks once per change to this file[/]"
    )
    return {"config_path": str(config_path)}


def _configure_bob(ctx: HarnessContext, transport: dict[str, str]) -> dict[str, Any]:
    """Register the hub's MCP server in ``.bob/mcp.json``.

    Both Bobs read this file but declare a streamable-HTTP server differently,
    so the transport keys come from the caller. Unlike Cursor, Bob takes the
    server's enabled state and the tool approval from the file, so there is no
    manual step left to the user.
    """
    from skore_cli._style import console
    from skore_cli.agent._skore_file import ensure_gitignore_entry

    config_dir = ctx.workspace / ".bob"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "mcp.json"

    config = _load_json_object(config_path)
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[SKORE_PROVIDER_KEY] = {
        **transport,
        "headers": {"Authorization": f"Bearer {ctx.api_key}"},
        "alwaysAllow": ["skore_agent"],
        "disabled": False,
    }
    config["mcpServers"] = servers
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    ensure_gitignore_entry(ctx.workspace, ".bob/mcp.json")

    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    return {"config_path": str(config_path)}


def _configure_bob_shell(ctx: HarnessContext) -> dict[str, Any]:
    """Configure Bob Shell, which reads a streamable-HTTP server from ``httpURL``."""
    # A plain `url` would be read as the legacy SSE endpoint, which the hub does
    # not serve.
    return _configure_bob(ctx, {"httpURL": ctx.mcp_url})


def _configure_bob_ide(ctx: HarnessContext) -> dict[str, Any]:
    """Configure Bob IDE, which reads a streamable-HTTP server from ``type``/``url``."""
    from skore_cli._style import console

    written = _configure_bob(ctx, {"type": "streamable-http", "url": ctx.mcp_url})
    console.print(
        "[skore.muted]  raise the network timeout for "
        f"[skore.skill]{SKORE_PROVIDER_KEY}[/] to 5 minutes under Settings -> MCP; a "
        "turn can outlast the 1 minute default[/]"
    )
    return written


def _copilot_provider(ctx: HarnessContext) -> dict[str, Any]:
    """Build the Custom Endpoint provider entry for VS Code Copilot Chat."""
    return {
        "name": COPILOT_PROVIDER_NAME,
        "vendor": "customendpoint",
        "apiKey": "skore",
        "apiType": "chat-completions",
        "models": [
            {
                "id": ctx.model_id,
                "name": COPILOT_PROVIDER_NAME,
                "url": f"{ctx.base_url}/chat/completions",
                "toolCalling": True,
                "vision": False,
                "maxInputTokens": 200000,
                "maxOutputTokens": 8192,
                "requestHeaders": {"X-API-Key": ctx.api_key},
            }
        ],
    }


def _configure_copilot(ctx: HarnessContext) -> dict[str, Any]:
    """Write ``.vscode/chatLanguageModels.json`` for GitHub Copilot in VS Code."""
    from skore_cli._style import console
    from skore_cli.agent._skore_file import ensure_gitignore_entry

    config_path = ctx.workspace / COPILOT_PROJECT_CONFIG
    _upsert_copilot_provider(config_path, _copilot_provider(ctx))
    ensure_gitignore_entry(ctx.workspace, COPILOT_PROJECT_CONFIG)
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    return {"config_path": str(config_path)}


def _resolve_copilot_binary() -> str | None:
    """Return the preferred VS Code binary available on PATH."""
    for name in COPILOT_BINARIES:
        if shutil.which(name) is not None:
            return name
    return None


def _vscode_app_dirname(binary: str) -> str:
    return "Code - Insiders" if binary == "code-insiders" else "Code"


def _copilot_user_config_path(binary: str, *, home: Path | None = None) -> Path:
    """Return the user-profile language-model configuration path."""
    home = home or Path.home()
    app = _vscode_app_dirname(binary)
    if sys.platform == "darwin":
        return (
            home
            / "Library"
            / "Application Support"
            / app
            / "User"
            / "chatLanguageModels.json"
        )
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / app / "User" / "chatLanguageModels.json"
    return home / ".config" / app / "User" / "chatLanguageModels.json"


def _upsert_copilot_provider(config_path: Path, provider: dict[str, Any]) -> None:
    """Upsert the Skore provider into a language-model file."""
    providers: list[Any] = []
    if config_path.is_file():
        try:
            parsed = json.loads(config_path.read_text() or "[]")
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"could not parse {config_path}; "
                "fix the file or add the Skore Agent provider manually."
            ) from error
        if not isinstance(parsed, list):
            raise RuntimeError(
                f"could not parse {config_path}; "
                "fix the file or add the Skore Agent provider manually."
            )
        providers = parsed
    updated = [
        entry
        for entry in providers
        if not (isinstance(entry, dict) and entry.get("name") == COPILOT_PROVIDER_NAME)
    ]
    updated.append(provider)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(updated, indent=2) + "\n")


def _toml_string(value: str) -> str:
    """Quote ``value`` as a TOML basic string.

    JSON string escapes are a valid subset of TOML basic-string escapes, so
    values containing quotes or backslashes stay parseable.
    """
    return json.dumps(value)


def _codex_config_overrides(base_url: str) -> list[str]:
    """Build the runtime ``--config`` overrides that declare the provider.

    Codex refuses ``model_providers`` in project-local config files, so the
    provider is passed per run instead. The API key is referenced through
    ``env_http_headers`` (header name -> environment variable): it travels in
    the process environment and never appears on the command line.
    """
    provider = f"model_providers.{CODEX_PROVIDER_KEY}"
    return [
        f"model_provider={_toml_string(CODEX_PROVIDER_KEY)}",
        f"{provider}.name={_toml_string(CODEX_PROVIDER_NAME)}",
        f"{provider}.base_url={_toml_string(base_url)}",
        f'{provider}.wire_api="responses"',
        f'{provider}.env_http_headers={{ "X-API-Key" = "{CODEX_API_KEY_ENV}" }}',
    ]


def _configure_codex(ctx: HarnessContext) -> dict[str, Any]:
    """Write the project-local Codex provider file.

    Everything lives in the workspace so each worktree keeps its own hub
    credentials; nothing is written under ``~/.codex`` and plain ``codex``
    runs keep the user's default model.
    """
    from skore_cli._style import console
    from skore_cli.agent._skore_file import ensure_gitignore_entry

    config_path = ctx.workspace / CODEX_PROJECT_CONFIG
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"model = {_toml_string(ctx.model_id)}\n"
        f"model_provider = {_toml_string(CODEX_PROVIDER_KEY)}\n"
        f"base_url = {_toml_string(ctx.base_url)}\n"
        f"api_key = {_toml_string(ctx.api_key)}\n"
    )
    ensure_gitignore_entry(ctx.workspace, CODEX_PROJECT_CONFIG)
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    console.print(
        "[skore.muted]Note:[/] configuration is project-local and "
        "[skore.path]~/.codex[/] [skore.muted]is untouched. Launch through[/] "
        "[skore.skill]skore agent[/] [skore.muted]to use the Skore hub model.[/]"
    )
    return {"config_path": str(config_path)}


def _launch_opencode(_workspace: Path, model_id: str) -> None:
    _exec_harness(
        "opencode",
        ["opencode", "-m", f"{SKORE_PROVIDER_KEY}/{model_id}"],
    )


def _launch_claude(workspace: Path, _model_id: str) -> None:
    env = os.environ.copy()
    settings_path = workspace / ".claude" / "settings.local.json"
    if settings_path.is_file():
        settings = json.loads(settings_path.read_text() or "{}")
        env.update(settings.get("env", {}))
    _exec_harness("claude", ["claude"], env=env)


def _launch_pi(workspace: Path, model_id: str) -> None:
    env = os.environ.copy()
    env["PI_CODING_AGENT_DIR"] = str(workspace / ".pi" / "agent")
    _exec_harness(
        "pi",
        ["pi", "--provider", SKORE_PROVIDER_KEY, "--model", model_id],
        env=env,
    )


def _launch_cursor(workspace: Path, _model_id: str) -> None:
    _exec_harness("cursor", ["cursor", str(workspace)])


def _launch_bob_shell(_workspace: Path, _model_id: str) -> None:
    _exec_harness("bob", ["bob"])


def _launch_bob_ide(workspace: Path, _model_id: str) -> None:
    if sys.platform == "darwin":
        _exec_harness("open", ["open", "-a", str(BOB_IDE_APP_PATH), str(workspace)])
    else:
        _exec_harness("bob-ide", ["bob-ide", str(workspace)])


def _launch_copilot(workspace: Path, _model_id: str) -> None:
    from skore_cli._style import console

    binary = _resolve_copilot_binary()
    if binary is None:
        raise RuntimeError("GitHub Copilot is not installed or not on PATH.")

    # VS Code only reads providers from the user profile, so the project config
    # written by ``_configure_copilot`` has to be mirrored there.
    project_config = workspace / COPILOT_PROJECT_CONFIG
    if not project_config.is_file():
        raise RuntimeError(
            f"missing {COPILOT_PROJECT_CONFIG}; "
            "run skore agent --harness copilot first."
        )
    try:
        providers = json.loads(project_config.read_text() or "[]")
    except json.JSONDecodeError as error:
        raise RuntimeError(f"could not parse {COPILOT_PROJECT_CONFIG}.") from error
    provider = next(
        (
            entry
            for entry in providers
            if isinstance(entry, dict) and entry.get("name") == COPILOT_PROVIDER_NAME
        ),
        None,
    )
    if provider is None:
        raise RuntimeError(
            f"{COPILOT_PROJECT_CONFIG} has no {COPILOT_PROVIDER_NAME} provider; "
            "run skore agent --harness copilot first."
        )
    user_config = _copilot_user_config_path(binary)
    _upsert_copilot_provider(user_config, provider)
    console.print(f"[skore.ok]+[/] synced [skore.path]{user_config}[/]")
    console.print(
        "[skore.muted]Select[/] [skore.skill]Skore Agent[/] "
        "[skore.muted]in Copilot Chat (reload VS Code if it is missing).[/]"
    )
    _exec_harness(binary, [binary, str(workspace)])


def _launch_codex(workspace: Path, model_id: str) -> None:
    project_config = workspace / CODEX_PROJECT_CONFIG
    if not project_config.is_file():
        raise RuntimeError(
            f"missing {CODEX_PROJECT_CONFIG}; run skore agent --harness codex first."
        )
    try:
        data = tomllib.loads(project_config.read_text())
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(
            f"could not parse {CODEX_PROJECT_CONFIG}; "
            "run skore agent --harness codex first."
        ) from error
    base_url = data.get("base_url")
    api_key = data.get("api_key")
    if not isinstance(base_url, str) or not base_url:
        raise RuntimeError(f"{CODEX_PROJECT_CONFIG} is missing a valid base_url.")
    if not isinstance(api_key, str) or not api_key:
        raise RuntimeError(f"{CODEX_PROJECT_CONFIG} is missing a valid api_key.")
    model = data.get("model")
    if not isinstance(model, str) or not model:
        model = model_id
    env = os.environ.copy()
    env[CODEX_API_KEY_ENV] = api_key
    argv = ["codex", "--model", model]
    for override in _codex_config_overrides(base_url):
        argv.extend(["--config", override])
    _exec_harness("codex", argv, env=env)


def _export_sdk_credentials(workspace: Path) -> None:
    """Publish the ``.skore`` credentials the ``skore`` package reads.

    The harness config only authenticates the harness itself. ``skore.login()``
    looks the API key up in ``SKORE_HUB_API_KEY`` and otherwise falls back to an
    interactive browser flow, so every experiment process the agent spawns would
    open its own OAuth tab. Values already present in the environment win, so a
    user's own key or hub keeps precedence.
    """
    from skore_cli.agent._skore_file import SkoreConfig

    config = SkoreConfig.load(workspace)
    if config is None:
        return
    os.environ.setdefault(SDK_API_KEY_ENV, config.api_key)
    os.environ.setdefault(SDK_URI_ENV, config.hub_url)


def _exec_harness(
    name: str, argv: list[str], *, env: dict[str, str] | None = None
) -> None:
    executable = shutil.which(argv[0])
    if executable is None:
        raise RuntimeError(f"{name} is not installed or not on PATH.")
    os.execve(executable, argv, env or os.environ)


AGENTS: dict[str, Agent] = {
    "agents": Agent(
        name="agents",
        label="Agents",
        user_skills_dir=".agents/skills",
        project_skills_dir=".agents/skills",
    ),
    "claude-code": Agent(
        name="claude-code",
        label="Claude Code",
        env_var="CLAUDECODE",
        detection_priority=0,
        user_skills_dir=".claude/skills",
        project_skills_dir=".claude/skills",
        harness_name="claude",
        harness_label="Claude",
        configure=_configure_claude,
        launch=_launch_claude,
    ),
    "cursor": Agent(
        name="cursor",
        label="Cursor",
        env_var="CURSOR_AGENT",
        detection_priority=1,
        user_skills_dir=".cursor/skills",
        project_skills_dir=".cursor/skills",
        harness_name="cursor",
        harness_label="Cursor",
        configure=_configure_cursor,
        launch=_launch_cursor,
    ),
    "codex": Agent(
        name="codex",
        label="Codex CLI",
        env_var="CODEX_SANDBOX",
        detection_priority=3,
        user_skills_dir=".agents/skills",
        project_skills_dir=".agents/skills",
        harness_name="codex",
        harness_label="Codex",
        configure=_configure_codex,
        launch=_launch_codex,
    ),
    "gemini": Agent(
        name="gemini",
        label="Gemini CLI",
        env_var="GEMINI_CLI",
        detection_priority=2,
        user_skills_dir=".gemini/skills",
        project_skills_dir=".agents/skills",
    ),
    "opencode": Agent(
        name="opencode",
        label="OpenCode",
        env_var="OPENCODE_CLIENT",
        detection_priority=5,
        skill_target=DEFAULT_AGENT,
        harness_name="opencode",
        configure=_configure_opencode,
        launch=_launch_opencode,
    ),
    "pi": Agent(
        name="pi",
        label="Pi",
        env_var="PI_CODING_AGENT",
        detection_priority=4,
        skill_target=DEFAULT_AGENT,
        harness_name="pi",
        configure=_configure_pi,
        launch=_launch_pi,
    ),
    "github-copilot": Agent(
        name="github-copilot",
        label="GitHub Copilot",
        harness_name="copilot",
        harness_binaries=COPILOT_BINARIES,
        configure=_configure_copilot,
        launch=_launch_copilot,
    ),
    "bob": Agent(
        name="bob",
        label="Bob Shell",
        harness_name="bob",
        harness_label="Bob Shell",
        configure=_configure_bob_shell,
        launch=_launch_bob_shell,
    ),
    "bob-ide": Agent(
        name="bob-ide",
        label="Bob IDE",
        harness_name="bob-ide",
        harness_label="Bob IDE",
        harness_binaries=("bob-ide",),
        configure=_configure_bob_ide,
        launch=_launch_bob_ide,
    ),
}

SKILL_AGENT_NAMES = [
    agent.name for agent in AGENTS.values() if agent.project_skills_dir is not None
]
HARNESS_NAMES = [
    agent.harness_name for agent in AGENTS.values() if agent.harness_name is not None
]


def detect_agent() -> Agent | None:
    """Return the calling agent detected from the environment, if any."""
    detectable = sorted(
        (agent for agent in AGENTS.values() if agent.env_var is not None),
        key=lambda agent: (
            agent.detection_priority
            if agent.detection_priority is not None
            else len(AGENTS)
        ),
    )
    for agent in detectable:
        if os.environ.get(agent.env_var or "", ""):
            return agent
    return None


def is_non_interactive() -> bool:
    """Return whether the CLI should avoid TUIs and emit plain-text output."""
    if os.environ.get("CI"):
        return True
    if detect_agent() is not None:
        return True
    return not (sys.stdin.isatty() and sys.stdout.isatty())


def resolve_skill_agent(agent: Agent) -> Agent:
    """Return the registry row that owns ``agent``'s skills directories."""
    target = AGENTS[agent.skill_target] if agent.skill_target else agent
    if target.user_skills_dir is None or target.project_skills_dir is None:
        raise ValueError(f"{agent.name} has no skills target")
    return target


def resolve_targets(
    agent_names: list[str],
    *,
    global_: bool,
    home: Path | None = None,
    cwd: Path | None = None,
) -> list[tuple[str, Path]]:
    """Resolve skill agent names to unique global or project directories."""
    home = home or Path.home()
    cwd = cwd or Path.cwd()

    targets: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for name in agent_names:
        agent = resolve_skill_agent(AGENTS[name])
        subdir = agent.user_skills_dir if global_ else agent.project_skills_dir
        assert subdir is not None
        path = (home if global_ else cwd) / subdir
        if path in seen:
            continue
        seen.add(path)
        targets.append((name, path))
    return targets


def get_harness(name: str) -> Agent:
    """Return the agent that provides the named harness."""
    for agent in AGENTS.values():
        if agent.harness_name == name:
            return agent
    raise KeyError(name)


def normalize_harness_name(name: str | None) -> str | None:
    """Return the current harness name for a persisted agent or harness name."""
    if name is None:
        return None
    for agent in AGENTS.values():
        if agent.harness_name and name in (agent.name, agent.harness_name):
            return agent.harness_name
    return name


def is_harness_installed(agent: Agent) -> bool:
    """Return whether ``agent``'s harness executable is on ``PATH``."""
    if agent.harness_name == "bob-ide" and sys.platform == "darwin":
        return BOB_IDE_APP_PATH.is_dir()
    binaries = agent.harness_binaries or (
        (agent.harness_name,) if agent.harness_name else ()
    )
    return any(shutil.which(binary) for binary in binaries)


def installed_harnesses() -> list[Agent]:
    """Return harness-capable agents whose executables are on ``PATH``."""
    return [
        agent
        for agent in AGENTS.values()
        if agent.harness_name is not None and is_harness_installed(agent)
    ]


def launch_harness(
    agent: Agent, workspace: Path, *, model_id: str = DEFAULT_MODEL_ID
) -> None:
    """Launch ``agent``'s harness in ``workspace``."""
    from skore_cli._style import console

    if not is_harness_installed(agent):
        raise RuntimeError(
            f"{agent.harness_display_name} is not installed or not on PATH."
        )
    if agent.launch is None:
        raise RuntimeError(f"{agent.name} has no harness launcher.")
    console.print(
        f"[skore.ok]Launching[/] [skore.skill]{agent.harness_display_name}[/] ..."
    )
    _export_sdk_credentials(workspace)
    agent.launch(workspace, model_id)
