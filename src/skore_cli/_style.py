"""Shared CLI styling: theme-agnostic ANSI colors and rich-click config."""

from __future__ import annotations

import rich.box
import rich_click as click
from rich.console import Console
from rich.theme import Theme

from skore_cli._agents import is_non_interactive

# Static slant-style wordmark for the top-level `skore` welcome output.
SKORE_BANNER = r"""
   _____ __ __ ____  ____  ______
  / ___// //_// __ \/ __ \/ ____/
  \__ \/ ,<  / / / / /_/ / __/
 ___/ / /| |/ /_/ / _, _/ /___
/____/_/ |_|\____/_/ |_/_____/
"""

console = Console(
    theme=Theme(
        {
            "skore.skill": "cyan",
            "skore.path": "blue",
            "skore.ok": "green",
            "skore.muted": "dim",
            "skore.cmd": "bold cyan",
        }
    )
)

click.rich_click.STYLE_OPTION = "cyan"
click.rich_click.STYLE_ARGUMENT = "cyan"
click.rich_click.STYLE_COMMAND = "bold cyan"
click.rich_click.STYLE_SWITCH = "green"
click.rich_click.STYLE_METAVAR = "yellow"
click.rich_click.STYLE_OPTIONS_PANEL_BORDER = "dim"
click.rich_click.STYLE_COMMANDS_PANEL_BORDER = "dim"
click.rich_click.STYLE_USAGE = "bold"
click.rich_click.STYLE_HELPTEXT = ""
click.rich_click.TEXT_MARKUP = "rich"
click.rich_click.STYLE_ERRORS_SUGGESTION = "dim"
click.rich_click.HEADER_TEXT = (
    "[bold cyan]skore[/]  [dim]· ML reporting & agent skills[/]"
)
click.rich_click.STYLE_HEADER_TEXT = ""

if is_non_interactive():
    click.rich_click.STYLE_OPTIONS_PANEL_BOX = rich.box.SIMPLE_HEAD
    click.rich_click.STYLE_COMMANDS_PANEL_BOX = rich.box.SIMPLE_HEAD
