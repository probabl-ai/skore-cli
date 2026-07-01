"""Harness registry, detection and per-harness configuration writers.

Supported harnesses: Claude, OpenCode and Pi. Each writer mirrors the
copy-pastable setup snippets from the Skore Hub agent-setup UI.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skore_cli._style import console

DEFAULT_MODEL_ID = "skore-agent"
OPENCODE_SCHEMA = "https://opencode.ai/config.json"
OPENCODE_PROVIDER_KEY = "skore"


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
    console.print(f"[skore.ok]+[/] wrote [skore.path]{config_path}[/]")
    return {"config_path": str(config_path)}


def _detect_opencode(_workspace: Path) -> bool:
    return shutil.which("opencode") is not None


def _detect_claude(_workspace: Path) -> bool:
    return shutil.which("claude") is not None


def _detect_pi(_workspace: Path) -> bool:
    return shutil.which("pi") is not None


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


def _exec_harness(name: str, argv: list[str], *, env: dict[str, str] | None = None) -> None:
    executable = shutil.which(argv[0])
    if executable is None:
        raise RuntimeError(f"{name} is not installed or not on PATH.")
    os.execve(executable, argv, env or os.environ)


_LAUNCHERS = {
    "claude": _launch_claude,
    "opencode": _launch_opencode,
    "pi": _launch_pi,
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
}

HARNESS_NAMES = list(HARNESSES)


def detect_harnesses(workspace: Path) -> list[str]:
    """Return harness names that look installed, in registry order."""
    return [name for name, harness in HARNESSES.items() if harness.detect(workspace)]
