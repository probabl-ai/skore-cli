"""Command-line interface for skore."""

from __future__ import annotations

import rich_click as click

import skore_cli._style  # noqa: F401  (applies the CLI palette and rich-click config)
from skore_cli._agents import (
    Agent,
    detect_agent,
    is_non_interactive,
    resolve_skill_agent,
)
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

_COMMANDS = [
    ("agent", "Authenticate, configure and launch a Skore Hub agent harness."),
    ("skills", "Install and manage Agent Skills from the probabl-ai/skills release."),
]


def _render_help(detected: Agent | None) -> str:
    """Build a plain-text help page, agent-flavored when ``detected`` is set."""
    lines = ["Skore command-line interface.", ""]

    if detected is not None:
        lines.append(f"Detected: {detected.label}")
        target = resolve_skill_agent(detected).project_skills_dir
        lines.append(f"Skills target: {target}")
        if detected.harness_name:
            lines.append(f"Harness: {detected.harness_display_name}")
        lines.append("")

    lines.append("Quick start:")

    if detected is not None:
        skill_target = resolve_skill_agent(detected).project_skills_dir
        lines.append(
            f"  skore skills install all      Install all skills to {skill_target}"
        )
    else:
        lines.append("  skore skills install all      Install all skills")
    lines.append("  skore skills install <ids>    Install specific skills by id")

    if detected is not None and detected.harness_name:
        label = detected.harness_display_name
        lines.append(
            f"  skore agent                   "
            f"Configure {label} with the Skore Hub provider"
        )
    else:
        lines.append(
            "  skore agent                   "
            "Configure and launch a Skore Hub agent harness"
        )

    lines.append("")
    lines.append("Commands:")
    for name, desc in _COMMANDS:
        lines.append(f"  {name:<7} {desc}")

    return "\n".join(lines)


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(package_name="skore-cli")
def cli(ctx) -> None:
    """Skore command-line interface."""
    if ctx.invoked_subcommand is None:
        if is_non_interactive():
            click.echo(_render_help(detect_agent()))
        else:
            console.print(f"[bold cyan]{SKORE_BANNER}[/]")
            click.echo(ctx.get_help())


cli.add_command(skills)
cli.add_command(agent)

# Commands contributed by other packages via the `skore_cli.plugins` entry-point
# group. Kept for third-party extensibility; the built-in `agent` command no
# longer goes through it so the CLI never imports `skore` just to show help.
load_plugins(cli)
