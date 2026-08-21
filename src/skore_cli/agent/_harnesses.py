"""Harness registry, detection and per-harness configuration writers.

Supported harnesses: Claude, OpenCode, Pi, GitHub Copilot and Codex. Each
writer mirrors the copy-pastable setup snippets from the Skore Hub agent-setup
UI.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skore_cli._style import console
from skore_cli.agent._skore_file import ensure_gitignore_entry

DEFAULT_MODEL_ID = "skore-agent"
OPENCODE_SCHEMA = "https://opencode.ai/config.json"
OPENCODE_PROVIDER_KEY = "skore"
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
COPILOT_PROVIDER_NAME = "Skore Agent"
COPILOT_PROJECT_CONFIG = ".vscode/chatLanguageModels.json"
COPILOT_BINARIES = ("code", "code-insiders")
CODEX_PROVIDER_KEY = "skore"
CODEX_PROVIDER_NAME = "Skore Agent"
CODEX_PROJECT_CONFIG = ".codex/skore-provider.toml"
CODEX_PROFILE_NAME = "skore"


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
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")

    # OpenCode auto-loads ``.opencode/plugins/``; the plugin stamps the
    # harness chat id on every LLM request so the hub can isolate sessions.
    plugin_path = ctx.workspace / OPENCODE_SESSION_PLUGIN
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_path.write_text(OPENCODE_SESSION_PLUGIN_SOURCE)
    ensure_gitignore_entry(ctx.workspace, OPENCODE_SESSION_PLUGIN)
    console.print(f"[skore.ok]+[/] wrote [skore.path]{plugin_path}[/]")
    return {"config_path": str(config_path), "plugin_path": str(plugin_path)}


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
                    # Send Pi's chat session id as ``x-session-id`` so the hub
                    # can key agent history per conversation.
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
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    return {"config_path": str(config_path)}


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
    _upsert_copilot_provider(config_path, _copilot_provider(ctx))
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


def _upsert_copilot_provider(config_path: Path, provider: dict[str, Any]) -> None:
    """Upsert the Skore provider into a language models file."""
    providers: list[Any] = []
    if config_path.is_file():
        try:
            parsed = json.loads(config_path.read_text() or "[]")
        except json.JSONDecodeError as error:
            # Overwriting would silently drop the other providers of the user.
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


def _detect_opencode(_workspace: Path) -> bool:
    return shutil.which("opencode") is not None


def _detect_claude(_workspace: Path) -> bool:
    return shutil.which("claude") is not None


def _detect_pi(_workspace: Path) -> bool:
    return shutil.which("pi") is not None


def _detect_copilot(_workspace: Path) -> bool:
    return _resolve_copilot_binary() is not None


def _detect_codex(_workspace: Path) -> bool:
    return shutil.which("codex") is not None


def _codex_profile_config_path(*, home: Path | None = None) -> Path:
    """Return the Codex profile file that selects the Skore provider.

    Codex reads all configuration from ``CODEX_HOME`` (default ``~/.codex``),
    so the profile file must live there even when the variable is overridden.
    """
    if home is None:
        codex_home = os.environ.get("CODEX_HOME")
        home = Path(codex_home) if codex_home else Path.home() / ".codex"
    return home / f"{CODEX_PROFILE_NAME}.config.toml"


def _toml_string(value: str) -> str:
    """Quote ``value`` as a TOML basic string.

    JSON string escapes are a valid subset of TOML basic-string escapes, so
    values containing quotes or backslashes stay parseable.
    """
    return json.dumps(value)


def _write_codex_profile(
    profile_path: Path, *, model_id: str, base_url: str, api_key: str
) -> None:
    """Write the standalone Skore profile loaded by ``codex --profile skore``.

    Codex only resolves ``model_providers`` from user-level configuration, so
    the provider lives in a dedicated profile file. Keeping it out of
    ``config.toml`` leaves plain ``codex`` on the user's default model.

    The key is embedded in the profile rather than read through ``env_key``:
    Codex refuses to start when the named variable is unset, and embedding
    keeps ``codex --profile skore`` usable outside ``skore agent``.
    """
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        f"model = {_toml_string(model_id)}\n"
        f"model_provider = {_toml_string(CODEX_PROVIDER_KEY)}\n"
        "\n"
        f"[model_providers.{CODEX_PROVIDER_KEY}]\n"
        f"name = {_toml_string(CODEX_PROVIDER_NAME)}\n"
        f"base_url = {_toml_string(base_url)}\n"
        'wire_api = "responses"\n'
        f'http_headers = {{ "X-API-Key" = {_toml_string(api_key)} }}\n'
    )


def _configure_codex(ctx: HarnessContext) -> dict[str, Any]:
    """Write project Codex provider file and the Skore Codex profile."""
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

    profile_path = _codex_profile_config_path()
    _write_codex_profile(
        profile_path,
        model_id=ctx.model_id,
        base_url=ctx.base_url,
        api_key=ctx.api_key,
    )
    console.print(f"[skore.ok]+[/] wrote [skore.path]{profile_path}[/]")
    console.print(
        "[skore.muted]Note:[/] [skore.path]config.toml[/] "
        "[skore.muted]is untouched: plain[/] [skore.skill]codex[/] "
        "[skore.muted]keeps your default model. Use[/] "
        f"[skore.skill]codex --profile {CODEX_PROFILE_NAME}[/] "
        "[skore.muted]to run the Skore hub model directly.[/]"
    )
    return {"config_path": str(config_path), "profile_path": str(profile_path)}


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


def _launch_copilot(workspace: Path, *, model_id: str) -> None:
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


def _launch_codex(workspace: Path, *, model_id: str) -> None:
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

    # Codex only resolves model_providers from user-level configuration, so
    # re-sync the dedicated profile file on every launch (same pattern as
    # Copilot, with the project file as the source of truth).
    profile_path = _codex_profile_config_path()
    _write_codex_profile(
        profile_path, model_id=model, base_url=base_url, api_key=api_key
    )
    console.print(f"[skore.ok]+[/] synced [skore.path]{profile_path}[/]")

    _exec_harness("codex", ["codex", "--profile", CODEX_PROFILE_NAME])


def _exec_harness(
    name: str, argv: list[str], *, env: dict[str, str] | None = None
) -> None:
    executable = shutil.which(argv[0])
    if executable is None:
        raise RuntimeError(f"{name} is not installed or not on PATH.")
    os.execve(executable, argv, env or os.environ)


_LAUNCHERS = {
    "claude": _launch_claude,
    "opencode": _launch_opencode,
    "pi": _launch_pi,
    "copilot": _launch_copilot,
    "codex": _launch_codex,
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
    "claude": Harness(
        "claude",
        "Claude",
        _detect_claude,
        _configure_claude,
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
    "codex": Harness(
        "codex",
        "Codex",
        _detect_codex,
        _configure_codex,
    ),
}

HARNESS_NAMES = list(HARNESSES)


def detect_harnesses(workspace: Path) -> list[str]:
    """Return harness names that look installed, in registry order."""
    return [name for name, harness in HARNESSES.items() if harness.detect(workspace)]
