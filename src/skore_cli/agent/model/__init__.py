"""The ``skore agent model`` command group (agent-as-model integration).

Exposes the Skore Hub agent as an OpenAI-compatible model: ``install`` wires a
local harness to the hub endpoint and ``status`` reports that wiring. Heavy
``skore``/``textual`` imports stay deferred inside the command callbacks.
"""

from skore_cli.agent.model._commands import model

__all__ = ["model"]
