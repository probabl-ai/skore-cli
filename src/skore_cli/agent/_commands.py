"""The ``skore agent`` click group: wires the integration subgroups.

The hub agent can be consumed two ways, each its own subgroup:

- ``skore agent model`` -- the agent is served behind an OpenAI-compatible
  endpoint and a local harness is pointed at it (agent-as-model).
- ``skore agent mcp`` -- a local MCP relay lets the harness's own assistant
  delegate ML tasks to the hub agent (agent-as-tool).

Both subgroups keep their heavy ``skore``/``textual``/``mcp`` imports deferred
inside their command callbacks so building the CLI (and ``--help``) stays cheap.
"""

from __future__ import annotations

import rich_click as click

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli agent": [
        {"name": "Integrations", "commands": ["model", "mcp"]},
    ],
}


@click.group(invoke_without_command=True)
@click.pass_context
def agent(ctx) -> None:
    """Connect this workspace to the Skore Hub agent (any harness)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# The integration subgroups. Imported here so they attach to the agent group;
# their heavy deps stay deferred inside their own callbacks.
from skore_cli.agent.mcp import mcp as _mcp_group  # noqa: E402
from skore_cli.agent.model import model as _model_group  # noqa: E402

agent.add_command(_model_group)
agent.add_command(_mcp_group)
