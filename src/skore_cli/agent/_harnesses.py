"""Harness registry, detection and per-harness configuration writers.

Supported harnesses: Bob Shell, Bob IDE, Claude, Cursor, OpenCode, Pi and GitHub
Copilot. Each writer mirrors the copy-pastable setup snippets from the Skore Hub
agent-setup UI.

Cursor and the two Bobs are the odd ones out: they talk to the hub's MCP
front-end rather than treating it as an OpenAI-compatible model provider, so they
are configured with a server URL instead of a base URL and a model id.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skore_cli._style import console
from skore_cli.agent._skore_file import ensure_gitignore_entry

DEFAULT_MODEL_ID = "skore-agent"
OPENCODE_SCHEMA = "https://opencode.ai/config.json"
OPENCODE_PROVIDER_KEY = "skore"
CURSOR_SERVER_KEY = "skore"
# Cursor concatenates the per-user and per-workspace allowlists, so this entry
# applies on top of whatever the user already allows. A convenience, not a
# security boundary.
CURSOR_ALLOWLIST_ENTRY = "skore:*"
CURSOR_AUTORUN_INSTRUCTIONS = (
    "curl fetching a Skore materialize URL under /v1/materialize/ to write a "
    "template or script into the workspace",
    "calls to the skore MCP server's skore_agent tool",
)
BOB_SERVER_KEY = "skore"
# Bob IDE ships as an application, with no documented command it installs on
# PATH; a module constant so tests can point it somewhere that does not exist.
BOB_IDE_APP_PATH = Path("/Applications/IBM Bob.app")
COPILOT_PROVIDER_NAME = "Skore Agent"
COPILOT_PROJECT_CONFIG = ".vscode/chatLanguageModels.json"
COPILOT_BINARIES = ("code", "code-insiders")


@dataclass(frozen=True)
class HarnessContext:
    """Inputs shared by every harness writer."""

    workspace: Path
    hub_url: str
    api_key: str
    model_id: str = DEFAULT_MODEL_ID

    @property
    def base_url(self) -> str:
        return f"{self.hub_url.rstrip('/')}/v1"

    @property
    def mcp_url(self) -> str:
        return f"{self.hub_url.rstrip('/')}/mcp"


def _configure_opencode(ctx: HarnessContext) -> dict[str, Any]:
    """Write ``opencode.json`` with the Skore Hub provider."""
    config_path = ctx.workspace / "opencode.json"
    config: dict[str, Any] = {
        "$schema": OPENCODE_SCHEMA,
        "model": f"{OPENCODE_PROVIDER_KEY}/{ctx.model_id}",
        "provider": {
            OPENCODE_PROVIDER_KEY: {
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
    return {"config_path": str(config_path)}


def _configure_claude(ctx: HarnessContext) -> dict[str, Any]:
    """Write ``.claude/settings.local.json`` for Claude."""
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
    config_dir = ctx.workspace / ".pi" / "agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "models.json"
    payload = {
        "providers": {
            "skore": {
                "baseUrl": ctx.base_url,
                "api": "openai-completions",
                "apiKey": ctx.api_key,
                "authHeader": True,
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
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
    servers[CURSOR_SERVER_KEY] = {
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
        f"[skore.muted]  turn [skore.skill]{CURSOR_SERVER_KEY}[/] on under "
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
    config_dir = ctx.workspace / ".bob"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "mcp.json"

    config = _load_json_object(config_path)
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[BOB_SERVER_KEY] = {
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
    written = _configure_bob(ctx, {"type": "streamable-http", "url": ctx.mcp_url})
    console.print(
        "[skore.muted]  raise the network timeout for "
        f"[skore.skill]{BOB_SERVER_KEY}[/] to 5 minutes under Settings -> MCP; a "
        "turn can outlast the 1 minute default[/]"
    )
    return written


def _copilot_provider(ctx: HarnessContext) -> dict[str, Any]:
    """Build the Custom Endpoint provider entry for VS Code Copilot Chat.

    VS Code treats ``apiKey`` as a keychain secret reference, so a raw hub key
    never reaches the wire. Auth is sent as a literal ``X-API-Key`` header
    instead; ``apiKey`` is only a schema placeholder (``minLength: 1``).
    """
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
    config_path = ctx.workspace / COPILOT_PROJECT_CONFIG
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [_copilot_provider(ctx)]
    config_path.write_text(json.dumps(payload, indent=2) + "\n")
    ensure_gitignore_entry(ctx.workspace, COPILOT_PROJECT_CONFIG)
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    return {"config_path": str(config_path)}


def _resolve_copilot_binary() -> str | None:
    """Return ``code`` or ``code-insiders`` when present on PATH."""
    for name in COPILOT_BINARIES:
        if shutil.which(name) is not None:
            return name
    return None


def _vscode_app_dirname(binary: str) -> str:
    return "Code - Insiders" if binary == "code-insiders" else "Code"


def _copilot_user_config_path(binary: str, *, home: Path | None = None) -> Path:
    """Return the user-profile ``chatLanguageModels.json`` for ``binary``."""
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


def _upsert_copilot_provider(user_config_path: Path, provider: dict[str, Any]) -> None:
    """Upsert the Skore provider into a user-level language models file."""
    providers: list[Any] = []
    if user_config_path.is_file():
        try:
            providers = json.loads(user_config_path.read_text() or "[]")
        except json.JSONDecodeError as error:
            # Overwriting would silently drop the other providers of the user.
            raise RuntimeError(
                f"could not parse {user_config_path}; "
                "add the Skore Agent provider from VS Code instead."
            ) from error
    updated = [
        entry
        for entry in providers
        if not (isinstance(entry, dict) and entry.get("name") == COPILOT_PROVIDER_NAME)
    ]
    updated.append(provider)
    user_config_path.parent.mkdir(parents=True, exist_ok=True)
    user_config_path.write_text(json.dumps(updated, indent=2) + "\n")


def _detect_opencode(_workspace: Path) -> bool:
    return shutil.which("opencode") is not None


def _detect_claude(_workspace: Path) -> bool:
    return shutil.which("claude") is not None


def _detect_pi(_workspace: Path) -> bool:
    return shutil.which("pi") is not None


def _detect_cursor(_workspace: Path) -> bool:
    # The macOS app bundle is not enough: `_launch_cursor` needs the CLI, which
    # only exists once the user runs "Shell Command: Install 'cursor' command".
    return shutil.which("cursor") is not None


def _detect_bob_shell(_workspace: Path) -> bool:
    return shutil.which("bob") is not None


def _detect_bob_ide(_workspace: Path) -> bool:
    # `_launch_bob_ide` opens the bundle rather than a command, so the bundle is
    # all that has to exist.
    return BOB_IDE_APP_PATH.is_dir()


def _detect_copilot(_workspace: Path) -> bool:
    return _resolve_copilot_binary() is not None


def launch_harness(
    name: str, workspace: Path, *, model_id: str = DEFAULT_MODEL_ID
) -> None:
    """Launch the named harness in ``workspace``."""
    harness = HARNESSES[name]
    if not harness.detect(workspace):
        raise RuntimeError(f"{harness.label} is not installed or not on PATH.")
    console.print(f"[skore.ok]Launching[/] [skore.skill]{harness.label}[/] ...")
    _LAUNCHERS[name](workspace, model_id=model_id)


def _launch_opencode(workspace: Path, *, model_id: str) -> None:
    _exec_harness(
        "opencode",
        ["opencode", "-m", f"{OPENCODE_PROVIDER_KEY}/{model_id}"],
    )


def _launch_claude(workspace: Path, *, model_id: str) -> None:
    env = os.environ.copy()
    settings_path = workspace / ".claude" / "settings.local.json"
    if settings_path.is_file():
        settings = json.loads(settings_path.read_text() or "{}")
        env.update(settings.get("env", {}))
    _exec_harness("claude", ["claude"], env=env)


def _launch_pi(workspace: Path, *, model_id: str) -> None:
    env = os.environ.copy()
    env["PI_CODING_AGENT_DIR"] = str(workspace / ".pi" / "agent")
    _exec_harness(
        "pi",
        ["pi", "--provider", OPENCODE_PROVIDER_KEY, "--model", model_id],
        env=env,
    )


def _launch_cursor(workspace: Path, *, model_id: str) -> None:
    _exec_harness("cursor", ["cursor", str(workspace)])


def _launch_bob_shell(workspace: Path, *, model_id: str) -> None:
    # Bob Shell takes the workspace from the working directory, like opencode.
    _exec_harness("bob", ["bob"])


def _launch_bob_ide(workspace: Path, *, model_id: str) -> None:
    _exec_harness("open", ["open", "-a", str(BOB_IDE_APP_PATH), str(workspace)])


def _launch_copilot(workspace: Path, *, model_id: str) -> None:
    binary = _resolve_copilot_binary()
    if binary is None:
        raise RuntimeError("GitHub Copilot is not installed or not on PATH.")

    # VS Code only reads providers from the user profile, so the project config
    # written by ``_configure_copilot`` has to be mirrored there.
    provider = json.loads((workspace / COPILOT_PROJECT_CONFIG).read_text())[0]
    user_config = _copilot_user_config_path(binary)
    _upsert_copilot_provider(user_config, provider)
    console.print(f"[skore.ok]+[/] synced [skore.path]{user_config}[/]")
    console.print(
        "[skore.muted]Select[/] [skore.skill]Skore Agent[/] "
        "[skore.muted]in Copilot Chat (reload VS Code if it is missing).[/]"
    )
    _exec_harness(binary, [binary, str(workspace)])


def _exec_harness(
    name: str, argv: list[str], *, env: dict[str, str] | None = None
) -> None:
    executable = shutil.which(argv[0])
    if executable is None:
        raise RuntimeError(f"{name} is not installed or not on PATH.")
    os.execve(executable, argv, env or os.environ)


_LAUNCHERS = {
    "bob": _launch_bob_shell,
    "bob-ide": _launch_bob_ide,
    "claude": _launch_claude,
    "cursor": _launch_cursor,
    "opencode": _launch_opencode,
    "pi": _launch_pi,
    "copilot": _launch_copilot,
}


@dataclass(frozen=True)
class Harness:
    """A configurable agent harness."""

    name: str
    label: str
    detect: Callable[[Path], bool]
    configure: Callable[[HarnessContext], dict[str, Any]]
    extras: tuple[str, ...] = field(default_factory=tuple)


HARNESSES: dict[str, Harness] = {
    "bob": Harness(
        "bob",
        "Bob Shell",
        _detect_bob_shell,
        _configure_bob_shell,
    ),
    "bob-ide": Harness(
        "bob-ide",
        "Bob IDE",
        _detect_bob_ide,
        _configure_bob_ide,
    ),
    "claude": Harness(
        "claude",
        "Claude",
        _detect_claude,
        _configure_claude,
    ),
    "cursor": Harness(
        "cursor",
        "Cursor",
        _detect_cursor,
        _configure_cursor,
    ),
    "opencode": Harness(
        "opencode",
        "OpenCode",
        _detect_opencode,
        _configure_opencode,
    ),
    "pi": Harness(
        "pi",
        "Pi",
        _detect_pi,
        _configure_pi,
    ),
    "copilot": Harness(
        "copilot",
        "GitHub Copilot",
        _detect_copilot,
        _configure_copilot,
    ),
}

HARNESS_NAMES = list(HARNESSES)


def detect_harnesses(workspace: Path) -> list[str]:
    """Return harness names that look installed, in registry order."""
    return [name for name, harness in HARNESSES.items() if harness.detect(workspace)]
