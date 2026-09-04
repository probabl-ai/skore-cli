# skore-cli

[![PyPI](https://img.shields.io/pypi/v/skore-cli)](https://pypi.org/project/skore-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/skore-cli)](https://pypi.org/project/skore-cli/)
[![Tests](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml/badge.svg)](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/probabl-ai/skore-cli/branch/main/graph/badge.svg)](https://codecov.io/gh/probabl-ai/skore-cli)
[![License](https://img.shields.io/pypi/l/skore-cli)](https://github.com/probabl-ai/skore-cli/blob/main/LICENSE)


```
   _____ __ __ ____  ____  ______
  / ___// //_// __ \/ __ \/ ____/
  \__ \/ ,<  / / / / /_/ / __/
 ___/ / /| |/ /_/ / _, _/ /___
/____/_/ |_|\____/_/ |_/_____/
```

Command-line interface for [skore](https://github.com/probabl-ai/skore).

`skore-cli` installs a single `skore` command with three areas:

- **skills** — discover, install and manage [Agent Skills](https://agentskills.io)
  from the [probabl-ai/skills](https://github.com/probabl-ai/skills) catalog
- **agent** — connect a project to the Skore Hub agent, write harness config
  and launch a local coding agent
- **sync** — synchronize report projects across local storage, Skore Hub, and MLflow

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

### Agent

On the first run, `skore agent` logs in when needed, lets you pick a workspace
and harness, creates a workspace API key, writes the harness configuration and
launches the agent. Supported harnesses: **Bob Shell**, **Bob IDE**, **Claude**,
**Cursor**, **OpenCode**, **Pi**, **GitHub Copilot** and **Codex** (all must be on
`PATH`; on macOS, Bob IDE is found via its application bundle). Later runs reuse
`.skore` in the project directory (gitignored). Use `SKORE_HUB_URI` (or
`--hub-url`) to point at a non-default hub.

Launching a harness exports the `.skore` credentials as `SKORE_HUB_API_KEY` and
`SKORE_HUB_URI`, so `skore.login()` in the scripts the agent runs authenticates
with that key instead of opening a browser. Values already set in your
environment are left untouched.

```bash
skore agent
skore agent --harness claude    # non-interactive harness choice
skore agent --workspace ./myapp # configure another project directory
```

### Sync

Synchronize a source project to a destination mode. The source defaults to local when
only `--to` is set; the destination defaults to local when only `--from` is set.

```bash
# Local -> Hub (add --both or --dry-run as needed)
SKORE_HUB_API_KEY=... skore sync experiment --to=hub --to-workspace=team

# Hub -> local with a different project name
SKORE_HUB_API_KEY=... skore sync production \
  --from=hub --from-workspace=team --to-project=downloaded

# Local -> MLflow
skore sync experiment --to=mlflow --tracking-uri=http://localhost:5000
```

Hub synchronization requires `SKORE_HUB_API_KEY`. Use `--hub-url` to target a custom
Hub API. Install `skore[mlflow]` to synchronize with MLflow.

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
