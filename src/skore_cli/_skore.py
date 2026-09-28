"""Lazy access to the (heavy, optional) ``skore`` package for the agent command.

The ``agent`` command reuses the authentication machinery that lives in
``skore`` (``skore._plugins.hub.authentication``). Importing it is expensive and
only needed when a command actually runs, so it is deferred here and surfaced as
a friendly error when ``skore`` is not installed.
"""

from __future__ import annotations

import importlib
import json
import os
import urllib.request
from collections.abc import Callable
from types import ModuleType
from urllib.error import HTTPError, URLError

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


def _discover_api_url(url: str) -> str | None:
    """Try to find the API URL behind a frontend URL.

    Fetch ``/.well-known/skore-hub.json`` from the given *url*. If the file
    exists and contains an ``api_url`` field, return it. Otherwise return
    ``None``.
    """
    discovery_url = url.rstrip("/") + "/.well-known/skore-hub.json"
    try:
        with urllib.request.urlopen(discovery_url, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                api_url = data.get("api_url")
                if api_url:
                    return api_url
    except (HTTPError, URLError, OSError, ValueError):
        pass
    return None


def resolve_hub_uri(
    hub_url: str | None, auth_fn: Callable[[str], ModuleType] = auth
) -> str:
    """Resolve the hub base URL.

    An explicit ``hub_url`` seeds the ``SKORE_HUB_URI`` environment variable;
    resolution then defers to ``skore``'s canonical ``URI()`` (which reads that
    env var, falling back to the public hub).

    If *hub_url* points at a frontend that serves
    ``/.well-known/skore-hub.json``, the API URL from that file is used instead
    of the passed URL.

    ``auth_fn`` defaults to :func:`auth` but is injectable so each command can
    pass the ``_auth`` accessor that its tests monkeypatch.
    """
    if hub_url:
        api_url = _discover_api_url(hub_url)
        resolved = api_url or hub_url
        os.environ[URI_ENV] = resolved
    return auth_fn("uri").URI()
