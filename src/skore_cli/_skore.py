"""Resolve a Hub URL, including one published by a frontend."""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.error import HTTPError, URLError

# Kept local so ``--help`` never imports the ``skore`` package.
URI_ENV = "SKORE_HUB_URI"


def _discover_api_url(url: str) -> str | None:
    """Return the API URL published at ``url/.well-known/skore-hub.json``."""
    discovery_url = url.rstrip("/") + "/.well-known/skore-hub.json"
    try:
        with urllib.request.urlopen(discovery_url, timeout=5) as response:
            if response.status == 200:
                api_url = json.loads(response.read().decode()).get("api_url")
                if api_url:
                    return api_url
    except (HTTPError, URLError, OSError, ValueError):
        pass
    return None


def resolve_hub_uri(hub_url: str | None) -> str:
    """Resolve ``hub_url`` and return ``skore``'s canonical hub URI.

    An explicit URL is written to ``SKORE_HUB_URI``. A frontend that serves
    ``/.well-known/skore-hub.json`` contributes its ``api_url`` instead.
    """
    if hub_url:
        os.environ[URI_ENV] = _discover_api_url(hub_url) or hub_url
    from skore._plugins.hub.authentication import URI

    return URI()
