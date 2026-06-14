"""Command-line interface for skore."""

from __future__ import annotations

import rich_click as click

import skore_cli._style  # noqa: F401  (applies the CLI palette and rich-click config)
from skore_cli._plugins import load_plugins

# These command modules defer their heavy `skore` imports into the callbacks, so
# importing them (to build the CLI / show `--help`) stays instant. Each merges its
# own `rich_click.COMMAND_GROUPS` entry, so import order does not matter.
from skore_cli.agent import agent
from skore_cli.hub import hub
from skore_cli.skills import skills


@click.group()
@click.version_option(package_name="skore-cli")
def cli() -> None:
    """Skore command-line interface."""


cli.add_command(skills)
cli.add_command(hub)
cli.add_command(agent)

# Commands contributed by other packages via the `skore_cli.plugins` entry-point
# group. Kept for third-party extensibility; the built-in `hub`/`agent` commands
# no longer go through it so the CLI never imports `skore` just to show help.
load_plugins(cli)
