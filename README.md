# skore-cli

Command-line interface for [skore](https://github.com/probabl-ai/skore).

`skore-cli` installs a single `skore` command with three areas:

- **skills** — discover, install and manage [Agent Skills](https://agentskills.io)
  from the [probabl-ai/skills](https://github.com/probabl-ai/skills) catalog
- **hub** — authenticate with a Skore Hub instance and manage workspaces, API
  keys and agent providers
- **agent** — connect a project to the Skore Hub agent, write harness config
  and launch a local coding agent

## Installation

```bash
pip install skore-cli
```

The base install is batteries-included: it bundles the `hub` and `agent`
features (so it pulls in `skore`). No extras are required.

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

### Hub

Authenticate with the hub via `skore hub login` (interactive device flow) or by
setting `SKORE_HUB_API_KEY`. Use `SKORE_HUB_URI` to point at a non-default hub.

```bash
skore hub login
skore hub status
skore hub api-key create   # workspace-scoped API keys
skore hub workspace list   # workspaces
skore hub agent-provider list
```

### Agent

On the first run, `skore agent` logs in when needed, lets you pick a workspace
and harness, creates a workspace API key, writes the harness configuration and
launches the agent. Supported harnesses: **Claude**, **OpenCode** and **Pi**
(must be on `PATH`). Later runs reuse `.skore` in the project directory
(gitignored).

```bash
skore agent
skore agent --harness claude    # non-interactive harness choice
skore agent --workspace ./myapp # configure another project directory
```

## License

MIT
