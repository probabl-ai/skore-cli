"""Command-line interface for skore."""

from __future__ import annotations

import rich_click as click

from skore_cli._plugins import load_plugins
from skore_cli._style import SKORE_BANNER, console

# These command modules defer their heavy `skore` imports into the callbacks, so
# importing them (to build the CLI / show `--help`) stays instant. Each merges its
# own `rich_click.COMMAND_GROUPS` entry, so import order does not matter.
from skore_cli.agent import agent
from skore_cli.skills import skills

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli": [
        {"name": "Agent", "commands": ["agent"]},
        {"name": "Skills", "commands": ["skills"]},
    ],
}


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(package_name="skore-cli")
def cli(ctx) -> None:
    """Skore command-line interface.

    Use ``skore agent`` to connect a project to the Skore Hub agent, and
    ``skore skills`` to install probabl-skills locally.
    """
    if ctx.invoked_subcommand is None:
        console.print(f"[bold cyan]{SKORE_BANNER}[/]")
        click.echo(ctx.get_help())


cli.add_command(skills)
cli.add_command(agent)

# Commands contributed by other packages via the `skore_cli.plugins` entry-point
# group. Kept for third-party extensibility; the built-in `agent` command no
# longer goes through it so the CLI never imports `skore` just to show help.
load_plugins(cli)
