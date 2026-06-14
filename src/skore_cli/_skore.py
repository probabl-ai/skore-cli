"""Lazy access to the (heavy, optional) ``skore`` package for hub/agent commands.

The ``hub`` and ``agent`` command groups reuse the authentication machinery that
lives in ``skore`` (``skore._plugins.hub.authentication``). Importing it is
expensive and only needed when a command actually runs, so it is deferred here
and surfaced as a friendly error when ``skore`` is not installed.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import rich_click as click

_MISSING = (
    "this command needs the `skore` package (install it with `pip install "
    "'skore-cli[agent]'` or `pip install skore`)."
)


def auth(submodule: str) -> ModuleType:
    """Import ``skore._plugins.hub.authentication.<submodule>`` or fail nicely."""
    try:
        return importlib.import_module(f"skore._plugins.hub.authentication.{submodule}")
    except ImportError as error:  # pragma: no cover - exercised via the CLI
        raise click.ClickException(_MISSING) from error
