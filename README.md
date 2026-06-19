# skore-cli

Command-line interface for [skore](https://github.com/probabl-ai/skore).

`skore-cli` lets you discover, install and manage [Agent
Skills](https://agentskills.io) for AI coding agents (Claude Code, Cursor,
Codex, Gemini, and the cross-client `.agents/` convention) directly from your
terminal.

## Installation

```bash
pip install skore-cli
```

The base install is batteries-included: it bundles the `hub`, `agent`, and
`agent mcp` features (so it pulls in `skore`, `pyyaml`, and the `mcp` SDK). No
extras are required.

## Usage

The package installs a `skore` command exposing a `skills` group:

```bash
skore skills find          # search the catalog interactively
skore skills list          # list installed skills
skore skills install       # install skills (interactive or by id)
skore skills update        # update installed skills
skore skills remove        # remove installed skills
```

Skills are installed into the current project by default; pass `--global`/`-g`
to target the user directory, and `--agent`/`-a` to select specific agents.

It also exposes a `hub` group (authenticate with a Skore Hub instance), an
`agent` group (wire a workspace to the Skore Hub agent for any harness), and
`agent mcp` (a local, harness-agnostic MCP relay that delegates ML tasks to the
hub agent). After a `skore hub login`, the relay lets your harness's assistant
delegate a task to the Skore agent, streams the agent's activity back, runs the
workspace actions it requests, and relays its user questions to you:

```bash
skore agent mcp install --host cursor   # register the relay with a host
skore agent mcp serve                   # the stdio relay the host launches
```

## License

MIT
