"""The ``skore agent`` command to connect a project to the Skore Hub agent.

The command authenticates with the hub, stores workspace credentials in a local
``.skore`` file, writes the harness configuration, and launches Bob, Claude,
Cursor, OpenCode, Pi or GitHub Copilot when installed.

Heavy ``skore`` (and ``textual``) imports are deferred into the command callback
so building the CLI (and ``--help``) never imports them.
"""

from skore_cli.agent._commands import agent

__all__ = ["agent"]
