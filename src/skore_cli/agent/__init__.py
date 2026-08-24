"""Commands to authenticate and connect a project to the Skore Hub agent.

``skore login`` stores workspace credentials in a local ``.skore`` file.
``skore agent`` writes the harness configuration and launches Claude, OpenCode,
Pi or GitHub Copilot when installed.

Heavy ``skore`` (and ``textual``) imports are deferred into the command callback
so building the CLI (and ``--help``) never imports them.
"""

from skore_cli.agent._commands import agent, login

__all__ = ["agent", "login"]
