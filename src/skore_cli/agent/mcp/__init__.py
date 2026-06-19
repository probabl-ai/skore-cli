"""The ``skore agent mcp`` command group: the delegation relay.

Exposes a local, harness-agnostic MCP relay (``skore agent mcp serve``) that lets
the user's outer LLM delegate a machine-learning task to the Skore Hub agent
after a Skore Hub login, through a single blocking ``skore_ml_run`` tool (no
polling). Internally the relay is an A2A client: it opens one durable task on the
hub and consumes a pushed SSE event stream. The hub agent (its own model +
skills) runs the orchestration server-side; whenever it defers a tool call, the
relay executes it locally (file/shell ops) or puts a skill-gate question to the
user via MCP elicitation, and streams the result back. The orchestration IP stays
on the hub.

``skore agent mcp install`` writes the per-host MCP configuration so the relay
launches the same way across every supported host.

Heavy imports (the ``mcp`` SDK, ``httpx``) are deferred into the command
callbacks so building the CLI (and ``--help``) never imports them.
"""

from skore_cli.agent.mcp._commands import mcp

__all__ = ["mcp"]
