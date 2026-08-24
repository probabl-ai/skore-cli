# skore-cli

[![PyPI](https://img.shields.io/pypi/v/skore-cli)](https://pypi.org/project/skore-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/skore-cli)](https://pypi.org/project/skore-cli/)
[![Tests](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml/badge.svg)](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/probabl-ai/skore-cli/branch/main/graph/badge.svg)](https://codecov.io/gh/probabl-ai/skore-cli)
[![License](https://img.shields.io/pypi/l/skore-cli)](https://github.com/probabl-ai/skore-cli/blob/main/LICENSE)

Command-line interface for [skore](https://github.com/probabl-ai/skore).

`skore-cli` installs a single `skore` command with three areas:

- **skills** — discover, install and manage [Agent Skills](https://agentskills.io)
  from the [probabl-ai/skills](https://github.com/probabl-ai/skills) catalog
- **agent** — connect a project to the Skore Hub agent, write harness config
  and launch a local coding agent
- **login** — authenticate a project with Skore Hub

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
skore skills list          # list installed skills
skore skills install       # install skills (interactive or by id)
skore skills update        # update installed skills
skore skills remove        # remove installed skills
```

### Login and agent

Run `skore login` from a terminal to authenticate, pick a Hub workspace and
create the project-local API key in `.skore` (gitignored). Then `skore agent`
configures and launches **Claude**, **OpenCode**, **Pi** or **GitHub Copilot**
(must be on `PATH`). An automated agent can skip interactive login when
`SKORE_HUB_API_KEY` is set. Use `SKORE_HUB_URI` (or `--hub-url`) to point at a
non-default hub.

```bash
skore login
skore agent
skore agent --harness claude    # non-interactive harness choice
skore agent --workspace ./myapp # configure another project directory
```

## Agent detection

When `skore` is run inside a coding agent, it detects the agent from
environment variables and adapts its behavior:

- **`skore`** (no args) shows an agent-specific quick-start with the detected
  agent's skill directory and harness
- **`skore skills install`** (no args, non-interactive) prints the catalog and
  the detected agent's skill directory — no `--agent` flag needed
- **`skore skills install all`** installs all skills into the detected
  agent's directory (also works with `--all`)
- **`skore skills install <ids>`** installs specific skills into the detected
  agent's directory
- **`skore agent`** (no `--harness`, non-interactive) auto-selects the
  detected agent's harness and skips the launch step (the agent is already
  running)

| Agent | Env Var |
|-------|---------|
| Claude Code | `CLAUDECODE` |
| Cursor | `CURSOR_AGENT` |
| Gemini CLI | `GEMINI_CLI` |
| Codex CLI | `CODEX_SANDBOX` |
| Pi | `PI_CODING_AGENT` |
| OpenCode | `OPENCODE_CLIENT` |

Any non-empty value triggers detection.

## License

MIT
