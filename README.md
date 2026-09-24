# skore-cli

[![PyPI](https://img.shields.io/pypi/v/skore-cli)](https://pypi.org/project/skore-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/skore-cli)](https://pypi.org/project/skore-cli/)
[![Tests](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml/badge.svg)](https://github.com/probabl-ai/skore-cli/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/probabl-ai/skore-cli/branch/main/graph/badge.svg)](https://codecov.io/gh/probabl-ai/skore-cli)
[![License](https://img.shields.io/pypi/l/skore-cli)](https://github.com/probabl-ai/skore-cli/blob/main/LICENSE)

Command-line interface for [skore](https://github.com/probabl-ai/skore).

`skore-cli` installs a single `skore` command with four areas:

- **skills** — discover, install and manage [Agent Skills](https://agentskills.io)
  from the [probabl-ai/skills](https://github.com/probabl-ai/skills) catalog
- **agent** — connect a project to the Skore Hub agent, write harness config
  and launch a local coding agent
- **hub** — generate, store and inspect Skore Hub API keys
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
`claude-code`, `cursor`, `codex`, `gemini`, `windsurf`, `cline`, `roo`, `amp`,
`github-copilot`, `bob`, `bob-ide`). Pass `--repo owner/name` on
**install** to pull from another GitHub catalog that ships `.catalog.json`
(the default is `probabl-ai/skills`). Interactive `skore skills install` also
lets you edit that `owner/name` in the wizard; `--repo` only pre-fills the
field. `list` and `update` reuse the stored source and show it in their output;
they do not take `--repo`.

`agents` is the cross-client default (`.agents/skills`). Other names write the
tool's native `SKILL.md` directory. Most global installs mirror that folder
under your home directory; Windsurf uses `~/.codeium/windsurf/skills`, Amp uses
`~/.config/agents/skills`, and Copilot in VSCode has no user-level skills
directory (`--global` is rejected). Bob Shell and Bob IDE share `.bob/skills`.

```bash
skore skills list          # list installed skills (with source)
skore skills install       # install skills (interactive or by id)
skore skills install --repo acme/skills gamma
skore skills update        # update from each skill's recorded source
skore skills remove        # remove installed skills
```

### Agent

On the first run, `skore agent` logs in when needed, lets you pick a workspace
and harness, and saves the workspace and hub URI to `.skore` in the project
directory (gitignored). The API key is not stored there: it comes from the
credential registry, and `skore agent` runs `skore hub api-key generate
--host=<host> --workspace=<workspace>` for you when no key is stored yet.

Supported harnesses: **Bob Shell**, **Bob IDE**, **Claude CLI**,
**Claude UI**, **Claude Plugin** (Cursor, VS Code, or VS Code Insiders),
**Cursor IDE**, **Cursor CLI**, **OpenCode**,
**Pi**, **Copilot in VSCode**, **Copilot CLI** and **Codex CLI**
(detected via `PATH`, the application bundle on macOS for Bob IDE and Claude UI,
or the Claude Code extension for Claude Plugin). The interactive picker lists
detected harnesses first, then the ones that are not installed.
`--harness claude` / `claude-cli` is the CLI; `claude-ui` is the desktop app.
`--harness claude-plugin` asks which IDE to open; `claude-plugin-cursor`,
`claude-plugin-code`, and `claude-plugin-code-insiders` select that IDE.
`--harness cursor` is Cursor IDE;
`cursor-cli` is the `agent` binary. Bob IDE also
accepts `--harness bobide` — the name of the command its installer puts on
`PATH` — as an alias for `--harness bob-ide`. Use `SKORE_HUB_URI` (or
`--hub-url`) to point at a non-default hub.

Reading `.skore` sets `SKORE_HUB_URI` so the `skore` package talks to the same
hub. The workspace API key stays in the credential registry and is picked up
automatically. `--hub-url` / `--host` override the URI for that process.

```bash
skore agent
skore agent --harness claude    # non-interactive harness choice
skore agent --workspace ./myapp # configure another project directory
```

### Hub

Store and inspect Hub API keys locally via skore's credential registry
(`~/.skore.hub/credentials.json`). `--host` selects a non-default hub (omit it
to use `SKORE_HUB_URI` or the public hub); `--workspace` is required when
generating or deleting a key.

```bash
skore hub api-key generate --workspace=<workspace>
skore hub api-key generate --host=<host> --workspace=<workspace>
skore hub api-key delete --workspace=<workspace>
skore hub api-key delete --host=<host> --workspace=<workspace>
skore hub api-key list
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

Hub synchronization uses `SKORE_HUB_API_KEY` when set, otherwise the key stored by
`skore hub api-key`. Use `--hub-url` to target a custom Hub API. Install
`skore[mlflow]` to synchronize with MLflow.

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
