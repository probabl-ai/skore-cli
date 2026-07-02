"""Entry-point plugin host for the ``skore`` CLI.

Lets other packages (``skore``, ``skore-hub``, ...) contribute command groups to
the ``skore`` CLI without ``skore-cli`` importing them directly. A plugin is a
Python entry point in the ``skore_cli.plugins`` group whose loaded object is
either a ``click.Command`` / ``click.Group`` or a zero-argument callable
returning one.

Example (in another package's ``pyproject.toml``)::

    [project.entry-points."skore_cli.plugins"]
    agent = "skore._cli.agent:agent"

Plugins that fail to load are skipped with a warning so a broken third-party
plugin never takes down the whole CLI.
"""

from __future__ import annotations

from importlib.metadata import entry_points

import rich_click as click

PLUGIN_GROUP = "skore_cli.plugins"


def _iter_plugin_entry_points():
    try:
        return list(entry_points(group=PLUGIN_GROUP))
    except TypeError:  # pragma: no cover - Python < 3.10 selection API
        return list(entry_points().get(PLUGIN_GROUP, []))


def load_plugins(group: click.Group) -> None:
    """Discover ``skore_cli.plugins`` entry points and attach their commands."""
    for entry_point in _iter_plugin_entry_points():
        try:
            obj = entry_point.load()
            command = obj if isinstance(obj, click.Command) else obj()
        except Exception as error:  # noqa: BLE001 - never break the CLI on a plugin
            click.echo(
                click.style(
                    f"warning: failed to load CLI plugin {entry_point.name!r}: {error}",
                    fg="yellow",
                ),
                err=True,
            )
            continue

        if isinstance(command, click.Command):
            group.add_command(command)
        else:
            click.echo(
                click.style(
                    f"warning: CLI plugin {entry_point.name!r} did not return a "
                    "click command; skipping",
                    fg="yellow",
                ),
                err=True,
            )
