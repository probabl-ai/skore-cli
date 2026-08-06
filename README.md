# skore-cli

[![PyPI](https://img.shields.io/pypi/v/skore-cli)](https://pypi.org/project/skore-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/skore-cli)](https://pypi.org/project/skore-cli/)
[![Tests](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml/badge.svg)](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/probabl-ai/skore-cli/branch/main/graph/badge.svg)](https://codecov.io/gh/probabl-ai/skore-cli)
[![License](https://img.shields.io/pypi/l/skore-cli)](https://github.com/probabl-ai/skore-cli/blob/main/LICENSE)

Command-line interface for [skore](https://github.com/probabl-ai/skore).

`skore-cli` installs a single `skore` command with two areas:

- **skills** — discover, install and manage [Agent Skills](https://agentskills.io)
  from the [probabl-ai/skills](https://github.com/probabl-ai/skills) catalog
- **agent** — connect a project to the Skore Hub agent, write harness config
  and launch a local coding agent

## Installation

```bash
pip install skore-cli
```

The base install is batteries-included: it bundles the `agent` feature (so it
pulls in `skore`). No extras are required.

## Usage

### Skills

Install skills into the current project by default. Pass `--global`/`-g` for a
user-wide install and `--agent`/`-a` to target specific agents (`agents`,
`claude-code`, `cursor`, `codex`, `gemini`).

```bash
skore skills find          # browse the catalog interactively
skore skills list          # list installed skills
skore skills install       # install skills (interactive or by id)
skore skills update        # update installed skills
skore skills remove        # remove installed skills
```

### Agent

On the first run, `skore agent` logs in when needed, lets you pick a workspace
and harness, creates a workspace API key, writes the harness configuration and
launches the agent. Supported harnesses: **Bob Shell**, **Bob IDE**, **Claude**,
**Cursor**, **OpenCode**, **Pi** and **GitHub Copilot** (all but Bob IDE must be
on `PATH`). Later runs reuse `.skore` in the project directory (gitignored). Use
`SKORE_HUB_URI` (or `--hub-url`) to point at a non-default hub.

```bash
skore agent
skore agent --harness claude    # non-interactive harness choice
skore agent --workspace ./myapp # configure another project directory
```

## License

MIT
