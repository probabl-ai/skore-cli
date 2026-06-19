"""Lazy access to the (heavy, optional) ``skore`` package for hub/agent commands.

The ``hub`` and ``agent`` command groups reuse the authentication machinery that
lives in ``skore`` (``skore._plugins.hub.authentication``). Importing it is
expensive and only needed when a command actually runs, so it is deferred here
and surfaced as a friendly error when ``skore`` is not installed.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from types import ModuleType

import rich_click as click

_MISSING = (
    "this command needs the `skore` package (install it with `pip install "
    "skore-cli` or `pip install skore`)."
)

# Mirrors ``skore._plugins.hub.authentication``'s env var; kept as a local literal
# so showing help never imports the (heavy) ``skore`` package.
URI_ENV = "SKORE_HUB_URI"


def auth(submodule: str) -> ModuleType:
    """Import ``skore._plugins.hub.authentication.<submodule>`` or fail nicely."""
    try:
        return importlib.import_module(f"skore._plugins.hub.authentication.{submodule}")
    except ImportError as error:  # pragma: no cover - exercised via the CLI
        raise click.ClickException(_MISSING) from error


def resolve_hub_uri(
    hub_url: str | None, auth_fn: Callable[[str], ModuleType] = auth
) -> str:
    """Resolve the hub base URL exactly like ``skore hub login``.

    An explicit ``hub_url`` seeds the ``SKORE_HUB_URI`` environment variable;
    resolution then defers to ``skore``'s canonical ``URI()`` (which reads that
    env var, falling back to the public hub). This keeps ``hub login``,
    ``agent init`` and ``agent mcp serve`` all pointing at the same hub.

    ``auth_fn`` defaults to :func:`auth` but is injectable so each command can
    pass the ``_auth`` accessor that its tests monkeypatch.
    """
    if hub_url:
        os.environ[URI_ENV] = hub_url
    return auth_fn("uri").URI()
