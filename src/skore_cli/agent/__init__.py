"""The ``skore agent`` command group to wire a workspace to the Skore Hub agent.

Architecture B (IP-isolated): an agent harness runs locally and is pointed at
``skore-hub`` as an OpenAI-compatible model provider. A PydanticAI agent on the
hub owns the orchestration and loads the probabl-skills *server-side*; the harness
only executes the tool calls the hub emits. Skills are therefore **not** installed
locally, keeping the orchestration IP on the hub.

The transport is a plain OpenAI-compatible model endpoint, so the agent is
harness-agnostic. ``skore agent init`` configures a specific harness for you: pass
``--harness <name>`` to do it non-interactively, or omit it in a terminal to pick
one interactively (mirroring ``skore skills``). A ``generic`` fallback just prints
the connection values for any other OpenAI-compatible client.

Heavy ``skore`` (and ``textual``) imports are deferred into the command callbacks
so building the CLI (and ``--help``) never imports them.
"""

from skore_cli.agent._commands import agent

__all__ = ["agent"]
