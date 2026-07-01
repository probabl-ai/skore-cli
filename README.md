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

The base install is batteries-included: it bundles the `hub` and `agent`
features (so it pulls in `skore`). No extras are required.

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

It also exposes a `hub` group (authenticate with a Skore Hub instance) and an
`agent` command (authenticate, configure and launch Claude Code, OpenCode or Pi
against the Skore Hub agent):

```bash
skore hub login
skore agent
```

After the first run, project credentials live in `.skore` (gitignored) and the
command reuses them on later runs.

## License

MIT
