"""The ``skore hub`` command group (authentication + workspace API keys).

Re-exports the ``hub`` click group. Heavy ``skore``/``httpx``/``textual``
imports stay deferred inside the command callbacks so building the CLI (and
``--help``) never imports them.
"""

from skore_cli.hub._commands import hub

__all__ = ["hub"]
