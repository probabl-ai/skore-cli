"""Per-host writers for ``skore agent mcp install``.

``skore agent mcp install --host <name>`` writes the configuration a given MCP
host needs to launch ``skore agent mcp serve`` over stdio. Hosts store MCP server
definitions differently (a project ``mcp.json``, an ``opencode.json`` block, a
global ``config.toml``), so each writer is bespoke. The resolved hub URL and
workspace are baked into the registered ``serve`` command so the relay points at
the same hub the user logged into.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skore_cli._style import console

# The MCP server id every host registers (the relay tool namespace).
SERVER_NAME = "skore-ml"

# The CLI subcommand the host launches over stdio.
LAUNCH_ARGS = ["agent", "mcp", "serve"]

# The executable the host invokes (the installed `skore` entry point).
EXECUTABLE = "skore"


@dataclass
class InstallContext:
    """Inputs for a host writer."""

    workspace: Path
    hub_url: str | None = None
    hub_workspace: str | None = None


def _serve_args(ctx: InstallContext) -> list[str]:
    """Build the ``serve`` argv, baking in the resolved hub URL/workspace."""
    args = list(LAUNCH_ARGS)
    if ctx.hub_url:
        args += ["--hub-url", ctx.hub_url]
    if ctx.hub_workspace:
        args += ["--hub-workspace", ctx.hub_workspace]
    return args


def _server_block_command(ctx: InstallContext) -> dict[str, Any]:
    """Return the standard ``{command, args}`` MCP server block."""
    return {"command": EXECUTABLE, "args": _serve_args(ctx)}


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        path.rename(path.with_suffix(path.suffix + ".bak"))
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _write_mcp_servers_json(path: Path, ctx: InstallContext) -> dict[str, Any]:
    """Merge a ``mcpServers`` entry into a JSON config (Cursor / Claude Code)."""
    config = _load_json(path)
    servers = config.setdefault("mcpServers", {})
    servers[SERVER_NAME] = _server_block_command(ctx)
    _write_json(path, config)
    return {"config": str(path)}


def _configure_cursor(ctx: InstallContext) -> dict[str, Any]:
    return _write_mcp_servers_json(ctx.workspace / ".cursor" / "mcp.json", ctx)


def _configure_claude_code(ctx: InstallContext) -> dict[str, Any]:
    return _write_mcp_servers_json(ctx.workspace / ".mcp.json", ctx)


def _configure_opencode(ctx: InstallContext) -> dict[str, Any]:
    """Write an ``mcp`` block into ``opencode.json`` (local stdio server)."""
    path = ctx.workspace / "opencode.json"
    config = _load_json(path)
    config.setdefault("$schema", "https://opencode.ai/config.json")
    mcp = config.setdefault("mcp", {})
    mcp[SERVER_NAME] = {
        "type": "local",
        "command": [EXECUTABLE, *_serve_args(ctx)],
        "enabled": True,
    }
    _write_json(path, config)
    return {"config": str(path)}


def _configure_codex(ctx: InstallContext) -> dict[str, Any]:
    """Append an idempotent ``[mcp_servers.skore-ml]`` block to ~/.codex/config.toml."""
    config_path = Path.home() / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    section = f"[mcp_servers.{SERVER_NAME}]"
    existing = config_path.read_text() if config_path.exists() else ""
    if section in existing:
        return {"config": str(config_path)}

    args = _serve_args(ctx)
    args_toml = ", ".join(json.dumps(arg) for arg in args)
    block = f'\n{section}\ncommand = "{EXECUTABLE}"\nargs = [{args_toml}]\n'
    with config_path.open("a") as handle:
        handle.write(block)
    return {"config": str(config_path)}


def _configure_generic(ctx: InstallContext) -> dict[str, Any]:
    """Print the launch command for any other MCP host to register manually."""
    command = " ".join([EXECUTABLE, *_serve_args(ctx)])
    console.print(
        "Register this stdio MCP server with your host (command):\n"
        f"  [skore.path]{command}[/]"
    )
    return {"command": command}


@dataclass
class Host:
    """A supported MCP host and its config writer."""

    name: str
    label: str
    writer: Callable[[InstallContext], dict[str, Any]]

    def configure(self, ctx: InstallContext) -> dict[str, Any]:
        return self.writer(ctx)


HOSTS: dict[str, Host] = {
    "cursor": Host("cursor", "Cursor  -  .cursor/mcp.json", _configure_cursor),
    "claude-code": Host(
        "claude-code", "Claude Code  -  .mcp.json", _configure_claude_code
    ),
    "opencode": Host(
        "opencode", "opencode  -  opencode.json (mcp block)", _configure_opencode
    ),
    "codex": Host("codex", "Codex  -  ~/.codex/config.toml", _configure_codex),
    "generic": Host(
        "generic", "generic  -  prints the launch command", _configure_generic
    ),
}

HOST_NAMES = list(HOSTS)


@dataclass(frozen=True)
class Installed:
    """A host's detected ``skore-ml`` relay registration."""

    name: str
    label: str
    config_path: Path
    present: bool
    serve_args: list[str] | None = None


def _codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _json_server_args(path: Path, *, key: str) -> list[str] | None:
    """Return the ``skore-ml`` server's args from a ``{key: {...}}`` JSON config.

    Used for the hosts that store a ``{command, args}`` block (Cursor / Claude
    Code, both under ``mcpServers``). Returns ``None`` when the entry is absent.
    """
    config = _load_json(path)
    entry = (config.get(key) or {}).get(SERVER_NAME)
    if not isinstance(entry, dict):
        return None
    args = entry.get("args")
    return list(args) if isinstance(args, list) else []


def _opencode_server_args(path: Path) -> list[str] | None:
    """Return the ``skore-ml`` args from ``opencode.json`` (``mcp`` block).

    opencode stores the launch command as a single ``command`` list
    ``[EXECUTABLE, *args]``; drop the executable to mirror the other hosts.
    """
    config = _load_json(path)
    entry = (config.get("mcp") or {}).get(SERVER_NAME)
    if not isinstance(entry, dict):
        return None
    command = entry.get("command")
    if isinstance(command, list) and command:
        return [str(part) for part in command[1:]]
    return []


def _codex_server_args(path: Path) -> list[str] | None:
    """Return the ``skore-ml`` args from ``~/.codex/config.toml``."""
    if not path.exists():
        return None
    try:
        config = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    entry = (config.get("mcp_servers") or {}).get(SERVER_NAME)
    if not isinstance(entry, dict):
        return None
    args = entry.get("args")
    return list(args) if isinstance(args, list) else []


def installed(workspace: Path) -> list[Installed]:
    """Detect which hosts have the ``skore-ml`` relay registered.

    Read-only: inspects each host's known config location (project files under
    ``workspace`` for Cursor/Claude Code/opencode, the global
    ``~/.codex/config.toml`` for Codex) and reports the baked ``serve`` args.
    The ``generic`` host has no file, so it is skipped.
    """
    cursor = workspace / ".cursor" / "mcp.json"
    claude = workspace / ".mcp.json"
    opencode = workspace / "opencode.json"
    codex = _codex_config_path()

    probes: list[tuple[str, Path, list[str] | None]] = [
        ("cursor", cursor, _json_server_args(cursor, key="mcpServers")),
        ("claude-code", claude, _json_server_args(claude, key="mcpServers")),
        ("opencode", opencode, _opencode_server_args(opencode)),
        ("codex", codex, _codex_server_args(codex)),
    ]

    results: list[Installed] = []
    for name, path, args in probes:
        results.append(
            Installed(
                name=name,
                label=HOSTS[name].label,
                config_path=path,
                present=args is not None,
                serve_args=args,
            )
        )
    return results
