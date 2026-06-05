"""Command-line interface for skore."""

from __future__ import annotations

import rich_click as click

import skore_cli._style  # noqa: F401  (applies the CLI palette and rich-click config)
from skore_cli.skills import skills


@click.group()
@click.version_option(package_name="skore-cli")
def cli() -> None:
    """Skore command-line interface."""


cli.add_command(skills)
