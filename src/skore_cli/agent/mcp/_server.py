"""The FastMCP relay backing ``skore agent mcp serve`` (no-poll, A2A-backed).

The user's outer LLM delegates a machine-learning task to the Skore Hub agent
through a SINGLE blocking tool:

* ``skore_ml_run(task)`` -- delegate a task and return only when it finishes.

There is no polling. Internally the relay opens one durable A2A task on the hub
(:mod:`_a2a_client`) and consumes a pushed SSE event stream. The hub agent (its
own model + skills) drives the orchestration server-side; whenever it defers tool
calls, the relay executes them locally (:mod:`_handlers`) -- file/shell ops on the
real workspace, and skill-gate questions put to the human via MCP elicitation --
and posts the results back, all within the one blocking call. Progress is streamed
to the user via ``ctx.info``/``ctx.report_progress`` (so the outer model is not
re-invoked just to relay activity), and the bulk of file/command output never
enters the outer LLM's context.

The server speaks MCP over stdio, so nothing here may write to stdout; logging
goes to stderr via the module logger.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from skore_cli.agent.mcp._a2a_client import RelayConfig
from skore_cli.agent.mcp._handlers import (
    ElicitationUnsupportedError,
    resolve_tool_calls,
)

logger = logging.getLogger("skore_cli.agent.mcp")

_SERVER_INSTRUCTIONS = """\
These tools delegate machine-learning engineering to the Skore agent -- a
specialized senior ML engineer for scikit-learn / tabular workflows (data
exploration, pipelines, cross-validation, metrics, model selection, experiment
tracking) that works in the current workspace.

Call skore_ml_run(task=<goal>) once and wait for it to return. It is a single
blocking call: the Skore agent runs the whole task server-side, the relay
performs any file/shell operations on the workspace itself, and any skill-gate
question is put to YOU/the user directly (via an interactive prompt) -- you never
read or write files and you never answer the agent's questions on the user's
behalf. The agent's progress is streamed to the user as it happens. When the call
returns, present the result; quote it rather than rephrasing. Let the Skore agent
decide the ML methodology; do not invent steps of your own.
"""

_RUN_DESCRIPTION = """\
Delegate a machine-learning engineering task to the Skore agent and return its
final result. This is a SINGLE blocking call -- there is no polling: it returns
only when the task is done (or fails). The relay performs all workspace file and
shell operations itself and surfaces any skill-gate question to the user
interactively, so you never read/write files and never answer those questions
yourself. `task` is the goal in natural language; `workspace` optionally overrides
the directory the agent acts in (defaults to the served workspace).
"""


async def _emit_progress(ctx: Context, text: str, step: int) -> None:
    """Stream an activity line to the user without re-invoking the outer model."""
    try:
        await ctx.info(text)
    except Exception:  # noqa: BLE001 - host may not support notifications
        logger.debug("ctx.info failed")
    # Keeps the blocking call alive on hosts that reset tool timeouts on progress;
    # harmless when the host ignores progress.
    with contextlib.suppress(Exception):
        await ctx.report_progress(progress=step, total=None, message=text[:120])


async def drive_task(ctx: Context, client: object, task: str, workspace: Path) -> str:
    """Drive one delegation task to completion over the A2A stream (no polling).

    Consumes the hub's pushed events; on ``input-required`` it executes the
    deferred tool calls locally (and elicits gates), posts the results back, and
    keeps streaming until a terminal event. Returns the final result text.
    """
    await _emit_progress(ctx, f"delegating to the Skore agent: {task[:80]}", 0)
    step = 0
    try:
        async for event in client.events(task):  # type: ignore[attr-defined]
            kind = event.get("kind")
            if kind == "activity":
                step += 1
                await _emit_progress(ctx, event.get("text", ""), step)
            elif kind == "input-required":
                results = await resolve_tool_calls(
                    ctx, client, workspace, event.get("tool_calls") or []
                )
                await client.send_results(results)  # type: ignore[attr-defined]
            elif kind == "result":
                return event.get("text", "") or (
                    "The Skore agent finished with no output."
                )
            elif kind == "error":
                return (
                    f"The Skore agent failed: {event.get('message', 'unknown error')}"
                )
        # Stream ended without an explicit result/error event.
        if client.state == "completed":  # type: ignore[attr-defined]
            return client.result or "The Skore agent finished with no output."
        if client.state == "failed":  # type: ignore[attr-defined]
            return f"The Skore agent failed: {client.error or 'unknown error'}"
        return f"The Skore agent stopped (state={client.state})."
    except ElicitationUnsupportedError as exc:
        await client.cancel()  # type: ignore[attr-defined]
        return f"Cannot complete the task: {exc}"
    except asyncio.CancelledError:
        await client.cancel()  # type: ignore[attr-defined]
        raise


def build_mcp_server(config: RelayConfig) -> FastMCP:
    """Build the FastMCP relay exposing the single ``skore_ml_run`` tool."""
    server = FastMCP("skore-ml", instructions=_SERVER_INSTRUCTIONS)

    @server.tool(name="skore_ml_run", description=_RUN_DESCRIPTION)
    async def skore_ml_run(
        task: str, ctx: Context, workspace: str | None = None
    ) -> str:
        target = Path(workspace).resolve() if workspace else config.default_workspace
        return await drive_task(ctx, config.make_client(), task, target)

    return server
