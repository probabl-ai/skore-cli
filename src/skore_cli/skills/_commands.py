"""The ``skore skills`` command group to manage Agent Skills."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import rich_click as click
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.tree import Tree

from skore_cli._agents import (
    DEFAULT_AGENT,
    SKILL_AGENT_NAMES,
    detect_agent,
    is_non_interactive,
    resolve_skill_agent,
    resolve_targets,
)
from skore_cli._style import console
from skore_cli.skills._catalog import GITHUB_REPO, fetch_release
from skore_cli.skills.app import (
    InstalledSkillsPicker,
    ProbablSkillsInstaller,
)

SIDECAR = ".skore-skill.json"
LOCAL_CATALOG = ".catalog.json"
LEGACY_CATALOG = "catalog.json"

click.rich_click.COMMAND_GROUPS = {
    **getattr(click.rich_click, "COMMAND_GROUPS", {}),
    "cli skills": [
        {"name": "Discover", "commands": ["list"]},
        {"name": "Manage", "commands": ["install", "update", "remove"]},
    ],
}


def _agent_option(func):
    return click.option(
        "--agent",
        "-a",
        multiple=True,
        type=click.Choice(SKILL_AGENT_NAMES),
        help="Target agent(s). Defaults to the .agents/ cross-client directory.",
    )(func)


def _global_option(func):
    return click.option(
        "--global",
        "-g",
        "global_",
        is_flag=True,
        help="Target the user directory instead of the current project.",
    )(func)


def _manage_agent_option(func):
    return click.option(
        "--agent",
        "-a",
        multiple=True,
        type=click.Choice(SKILL_AGENT_NAMES),
        help="Restrict to specific agent(s). Defaults to all known agents.",
    )(func)


def _manage_targets(agent: tuple[str, ...], *, global_: bool) -> list[tuple[str, Path]]:
    """Resolve the directories scanned by ``list``/``update``/``remove``.

    With no explicit ``--agent`` every known agent is scanned so that skills
    installed into any client directory remain discoverable and manageable.
    """
    agent_names = list(agent) if agent else SKILL_AGENT_NAMES
    try:
        return resolve_targets(agent_names, global_=global_, skip_missing=not agent)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


@contextmanager
def _release(repo: str = GITHUB_REPO) -> Iterator[tuple[str, Path, dict[str, Any]]]:
    """Fetch the latest release and clean up its extracted files afterwards.

    Surfaces network/parsing failures as a :class:`click.ClickException` rather
    than a raw traceback, and removes the temporary extraction directory once
    the wrapped command is done with it.
    """
    with console.status(
        f"Fetching latest skills release from {repo}...", spinner="dots"
    ):
        try:
            tag, root, catalog = fetch_release(repo)
        except (OSError, ValueError, KeyError) as error:
            raise click.ClickException(
                f"Could not fetch the latest skills release from GitHub "
                f"({repo}): {error}"
            ) from error

    try:
        yield tag, root, catalog
    finally:
        # ``download_release`` extracts into a dedicated temporary directory and
        # returns its single child, so ``root.parent`` is that temporary dir.
        shutil.rmtree(root.parent, ignore_errors=True)


def _skill_repository(sidecar: dict[str, Any]) -> str:
    """Return the GitHub ``owner/name`` recorded on an installed skill."""
    return sidecar.get("repository") or GITHUB_REPO


def _local_catalog_path(target: Path) -> Path | None:
    """Return the on-disk catalog file, preferring the hidden name."""
    hidden = target / LOCAL_CATALOG
    if hidden.is_file():
        return hidden
    legacy = target / LEGACY_CATALOG
    if legacy.is_file():
        return legacy
    return None


def _envelope_from_catalog_data(data: Any) -> dict[str, Any]:
    """Normalize a catalog file into the ``sources`` envelope.

    A file without ``sources`` is the previous single-repository snapshot.
    """
    if isinstance(data, dict) and "sources" in data:
        return data
    repo = GITHUB_REPO
    if isinstance(data, dict):
        repo = data.get("repository") or GITHUB_REPO
    return {"sources": {repo: data}}


def _read_local_catalog(target: Path) -> dict[str, Any]:
    """Load the per-target catalog envelope, or an empty sources map."""
    path = _local_catalog_path(target)
    if path is None:
        return {"sources": {}}
    return _envelope_from_catalog_data(json.loads(path.read_text()))


def _remove_legacy_catalog(target: Path) -> None:
    """Delete a leftover ``catalog.json`` after migrating to ``.catalog.json``."""
    legacy = target / LEGACY_CATALOG
    if legacy.is_file():
        legacy.unlink()


def _write_local_catalog(target: Path, envelope: dict[str, Any]) -> None:
    """Write the per-target catalog envelope to ``.catalog.json``."""
    target.mkdir(parents=True, exist_ok=True)
    (target / LOCAL_CATALOG).write_text(json.dumps(envelope, indent=2) + "\n")
    _remove_legacy_catalog(target)


def _persist_source_catalog(
    target: Path, repo: str, tag: str, catalog: dict[str, Any]
) -> None:
    """Merge ``catalog`` for ``repo`` into ``target``'s local ``.catalog.json``."""
    envelope = _read_local_catalog(target)
    envelope.setdefault("sources", {})[repo] = {
        **catalog,
        "repository": repo,
        "release": tag,
    }
    _write_local_catalog(target, envelope)


def _prune_local_catalog(target: Path) -> None:
    """Drop catalog sources that no longer have an installed skill in ``target``."""
    remaining = {_skill_repository(sidecar) for _, sidecar in _installed(target)}
    envelope = _read_local_catalog(target)
    sources = {
        repo: entry
        for repo, entry in envelope.get("sources", {}).items()
        if repo in remaining
    }
    path = target / LOCAL_CATALOG
    if not sources:
        if path.is_file():
            path.unlink()
        _remove_legacy_catalog(target)
        return
    envelope["sources"] = sources
    _write_local_catalog(target, envelope)


def _format_sources(repos: list[str]) -> str:
    """Join repository names for user-facing messages."""
    return ", ".join(repos)


def _index(catalog: dict[str, Any]) -> tuple[dict, dict]:
    skills = {skill["id"]: skill for skill in catalog.get("skills", [])}
    workflows = {workflow["id"]: workflow for workflow in catalog.get("workflows", [])}
    return skills, workflows


def _expand(ids: list[str], skills: dict, workflows: dict) -> list[dict]:
    selected: dict[str, dict] = {}
    for identifier in ids:
        if identifier in workflows:
            for skill_id in workflows[identifier].get("includes", []):
                skill = skills.get(skill_id)
                if skill is None:
                    raise click.ClickException(
                        f"Workflow {identifier!r} references unknown skill "
                        f"{skill_id!r}."
                    )
                selected[skill_id] = skill
        elif identifier in skills:
            selected[identifier] = skills[identifier]
        else:
            raise click.ClickException(f"Unknown skill or workflow: {identifier!r}")
    return list(selected.values())


def _install_skill(skill: dict, root: Path, target: Path, tag: str, repo: str) -> None:
    """Copy ``skill`` from the extracted release into ``target`` and write a sidecar."""
    source = root / skill["path"]
    destination = target / skill["id"]

    if destination.exists():
        shutil.rmtree(destination)

    shutil.copytree(source, destination)
    _write_sidecar(destination, skill, tag, repo)


def _write_sidecar(destination: Path, skill: dict, tag: str, repo: str) -> None:
    """Write ``.skore-skill.json`` for an installed skill directory."""
    sidecar = {
        "id": skill["id"],
        "release": tag,
        "hash": skill["hash"],
        "repository": repo,
    }
    (destination / SIDECAR).write_text(json.dumps(sidecar, indent=2))


def _installed(target: Path):
    """Yield ``(directory, sidecar)`` for each skill installed under ``target``."""
    if not target.is_dir():
        return

    for child in sorted(target.iterdir()):
        if not child.is_dir():
            continue
        sidecar = child / SIDECAR
        if sidecar.is_file():
            yield child, json.loads(sidecar.read_text())


def _installed_skill_ids(
    targets: list[tuple[str, Path]],
) -> list[str]:
    """Return sorted unique installed skill ids across the given targets."""
    ids: set[str] = set()
    for _, target in targets:
        for _, sidecar in _installed(target):
            ids.add(sidecar["id"])
    return sorted(ids)


def _installed_skill_sources(
    targets: list[tuple[str, Path]],
) -> dict[str, str]:
    """Map each installed skill id to a display string of its source repo(s)."""
    sources: dict[str, set[str]] = {}
    for _, target in targets:
        for _, sidecar in _installed(target):
            sources.setdefault(sidecar["id"], set()).add(_skill_repository(sidecar))
    return {
        skill_id: _format_sources(sorted(repos)) for skill_id, repos in sources.items()
    }


def _interactive_manage_picker(
    skill_ids: list[str],
    *,
    title: str,
    sources: dict[str, str] | None = None,
) -> list[str] | None:
    """Run the installed-skills picker and return the chosen ids."""
    if not skill_ids:
        console.print("No skills installed.")
        return None

    app = InstalledSkillsPicker(skill_ids, title=title, sources=sources)
    app.run()
    return app.result


def _matches(entry: dict, query: str) -> bool:
    fields = (
        entry.get("id"),
        entry.get("title"),
        entry.get("summary"),
        entry.get("category"),
    )
    return any(field and query in field.lower() for field in fields)


def _render_catalog(
    catalog: dict[str, Any],
    *,
    query: str | None = None,
    ids: list[str] | None = None,
) -> None:
    workflows = catalog.get("workflows", [])
    skills = catalog.get("skills", [])

    if ids is not None:
        wanted = set(ids)
        workflows = [entry for entry in workflows if entry["id"] in wanted]
        skills = [entry for entry in skills if entry["id"] in wanted]
    elif query:
        needle = query.lower()
        workflows = [entry for entry in workflows if _matches(entry, needle)]
        skills = [entry for entry in skills if _matches(entry, needle)]

    if is_non_interactive():
        _render_catalog_plain(workflows, skills)
        return

    if workflows:
        table = Table(title="Workflows (recommended)")
        table.add_column("id", style="skore.skill")
        table.add_column("summary")
        for workflow in workflows:
            table.add_row(workflow["id"], workflow.get("summary", ""))
        console.print(table)

    if skills:
        table = Table(title="Skills")
        table.add_column("id", style="skore.skill")
        table.add_column("summary")
        for skill in skills:
            table.add_row(skill["id"], skill.get("summary", ""))
        console.print(table)

    if not workflows and not skills:
        console.print("No skill or workflow matches the query.")


def _render_catalog_plain(
    workflows: list[dict[str, Any]], skills: list[dict[str, Any]]
) -> None:
    """Render the catalog as plain text (no boxes) for non-interactive use."""
    if workflows:
        console.print("Workflows:")
        for wf in workflows:
            summary = wf.get("summary", "")
            console.print(f"  {wf['id']:<26} {summary}")

    if skills:
        if workflows:
            console.print("")
        console.print("Skills:")
        for skill in skills:
            summary = skill.get("summary", "")
            console.print(f"  {skill['id']:<26} {summary}")

    if not workflows and not skills:
        console.print("No skill or workflow matches the query.")


def _resolve_agent_names(agent: tuple[str, ...]) -> list[str]:
    if agent:
        return list(agent)
    detected = detect_agent()
    if detected:
        return [resolve_skill_agent(detected).name]
    return [DEFAULT_AGENT]


def _interactive_install_options(
    *,
    agent: tuple[str, ...],
    default_global: bool,
    default_repo: str,
) -> tuple[list[dict], list[str], bool, str, str, Path, dict[str, Any]] | None:
    """Run the tabbed Textual wizard to choose source, skills, agents and scope.

    Parameters
    ----------
    agent : tuple of str
        Agents passed on the command line; when non-empty the agent step is
        skipped.
    default_global : bool
        The pre-selected scope (``True`` for the user-level directory).
    default_repo : str
        GitHub ``owner/name`` pre-filled in the source step.

    Returns
    -------
    tuple or None
        ``(selected_skills, agent_names, global_, repo, tag, root, catalog)``
        or ``None`` when the user aborts or selects nothing. ``root`` is an
        extracted release the caller must delete.
    """
    app = ProbablSkillsInstaller(
        agent=agent, default_global=default_global, default_repo=default_repo
    )
    app.run()

    if app.result is None:
        return None

    selected_ids, agent_names, global_, repo = app.result
    if (
        not selected_ids
        or not agent_names
        or app.catalog is None
        or app.root is None
        or app.tag is None
    ):
        if app.root is not None:
            shutil.rmtree(app.root.parent, ignore_errors=True)
        return None

    skills_by_id, workflows_by_id = _index(app.catalog)
    selected = _expand(selected_ids, skills_by_id, workflows_by_id)
    return selected, agent_names, global_, repo, app.tag, app.root, app.catalog


def _copy_selected_skills(
    selected: list[dict],
    agent_names: list[str],
    *,
    global_: bool,
    repo: str,
    tag: str,
    root: Path,
    catalog: dict[str, Any],
) -> int:
    """Copy ``selected`` skills into the resolved targets and persist catalogs."""
    try:
        targets = resolve_targets(agent_names, global_=global_)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    tree = Tree(f"Installing {len(selected)} skill(s) from {repo} release {tag}")
    for _, target in targets:
        branch = tree.add(f"[skore.path]{target}[/]")
        for skill in selected:
            branch.add(
                f"[skore.skill]{skill['id']}[/]  "
                f"[skore.muted]{skill.get('summary', '')}[/]"
            )
    console.print(tree)

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Installing", total=len(selected) * len(targets))
        for _, target in targets:
            for skill in selected:
                _install_skill(skill, root, target, tag, repo)
                progress.advance(task)
            _persist_source_catalog(target, repo, tag, catalog)

    return len(targets)


@click.group(invoke_without_command=True)
@click.pass_context
def skills(ctx) -> None:
    """Install and manage Agent Skills from the probabl-ai/skills release."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@skills.command("install")
@click.argument("ids", nargs=-1)
@_agent_option
@_global_option
@click.option(
    "--repo",
    "-r",
    default=GITHUB_REPO,
    show_default=True,
    help="GitHub owner/name of the skills catalog to install from.",
)
@click.option(
    "--all",
    "all_",
    is_flag=True,
    help="Install every skill from the latest release (non-interactive).",
)
def install(ids, agent, global_, repo, all_) -> None:
    """Install skill(s) or workflow(s) from the latest release.

    Run without arguments to launch the interactive installer (a tabbed wizard
    for the GitHub source, skill selection, target agent and install scope).

    Pass skill or workflow ids (or ``--all``) to install non-interactively,
    optionally with ``--agent`` and ``--global`` to choose the targets and
    scope. ``--agent``/``--global`` require an explicit selection.

    ``all`` can be passed as a positional argument instead of ``--all``:
    ``skore skills install all``.

    Use ``--repo owner/name`` to install from a catalog other than the default.
    In the interactive wizard that value is pre-filled and can still be edited.
    """
    ids = list(ids)
    if "all" in ids:
        all_ = True
        ids = [i for i in ids if i != "all"]

    interactive = not (ids or all_ or agent or global_)
    if interactive:
        if is_non_interactive():
            with _release(repo) as (_tag, _root, catalog):
                _render_catalog(catalog)
                console.print(
                    "Run [skore.cmd]skore skills install <ids>[/] to install "
                    "specific skills, or [skore.cmd]skore skills install all[/] "
                    "to install everything."
                )
            return
        options = _interactive_install_options(
            agent=agent, default_global=global_, default_repo=repo
        )
        if not options:
            console.print("Nothing selected.")
            return
        selected, agent_names, global_, repo, tag, root, catalog = options
        try:
            n_targets = _copy_selected_skills(
                selected,
                agent_names,
                global_=global_,
                repo=repo,
                tag=tag,
                root=root,
                catalog=catalog,
            )
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)
        console.print(
            f"[skore.ok]+[/] installed [skore.skill]{len(selected)}[/] skill(s) "
            f"into {n_targets} location(s) from {repo} release {tag}"
        )
        return

    if not (ids or all_):
        raise click.UsageError(
            "Specify skill/workflow ids or --all to install non-interactively."
        )

    with _release(repo) as (tag, root, catalog):
        skills_by_id, workflows_by_id = _index(catalog)
        selected = (
            list(skills_by_id.values())
            if all_
            else _expand(ids, skills_by_id, workflows_by_id)
        )
        agent_names = _resolve_agent_names(agent)
        n_targets = _copy_selected_skills(
            selected,
            agent_names,
            global_=global_,
            repo=repo,
            tag=tag,
            root=root,
            catalog=catalog,
        )

    console.print(
        f"[skore.ok]+[/] installed [skore.skill]{len(selected)}[/] skill(s) "
        f"into {n_targets} location(s) from {repo} release {tag}"
    )


@skills.command("list")
@_manage_agent_option
@_global_option
def list_skills(agent, global_) -> None:
    """List installed skills.

    Scans every known agent by default; pass ``--agent`` to restrict the scan.
    """
    targets = _manage_targets(agent, global_=global_)

    table = Table(title="Installed skills")
    table.add_column("id", style="skore.skill")
    table.add_column("release")
    table.add_column("source")
    table.add_column("location")

    found = False
    for _, target in targets:
        for _, sidecar in _installed(target):
            found = True
            table.add_row(
                sidecar["id"],
                sidecar.get("release", ""),
                _skill_repository(sidecar),
                str(target),
            )

    if found:
        console.print(table)
    else:
        console.print("No skills installed.")


@skills.command("update")
@click.argument("ids", nargs=-1)
@_manage_agent_option
@_global_option
@click.option("--all", "all_", is_flag=True, help="Update every installed skill.")
def update(ids, agent, global_, all_) -> None:
    """Update installed skills to the latest release of their recorded source.

    Pass skill ids to update, or ``--all`` to update every installed skill.
    Each skill is fetched from the GitHub repository stored at install time.
    Scans every known agent by default; pass ``--agent`` to restrict the scan.
    Run ``skore skills list`` to see installed ids.
    """
    targets = _manage_targets(agent, global_=global_)

    if not all_ and not ids:
        if not is_non_interactive():
            selected = _interactive_manage_picker(
                _installed_skill_ids(targets),
                title="Select skills to update.",
                sources=_installed_skill_sources(targets),
            )
            if not selected:
                console.print("Nothing selected.")
                return
            ids = selected
        else:
            raise click.UsageError(
                "Specify skill ids to update or pass --all. "
                "Run `skore skills list` to discover ids."
            )

    requested = set(ids)
    selected_items: list[tuple[Path, dict[str, Any]]] = []
    for _, target in targets:
        for _, sidecar in _installed(target):
            if not all_ and sidecar["id"] not in requested:
                continue
            selected_items.append((target, sidecar))

    updated: list[tuple[str, str, Path]] = []
    considered_repos = sorted(
        {_skill_repository(sidecar) for _, sidecar in selected_items}
    )
    for repo in considered_repos:
        with _release(repo) as (tag, root, catalog):
            skills_by_id, _ = _index(catalog)
            for target, sidecar in selected_items:
                if _skill_repository(sidecar) != repo:
                    continue
                skill = skills_by_id.get(sidecar["id"])
                if skill is None:
                    continue
                if sidecar.get("hash") != skill["hash"]:
                    _install_skill(skill, root, target, tag, repo)
                    updated.append((sidecar["id"], repo, target))
                else:
                    _write_sidecar(target / sidecar["id"], skill, tag, repo)
            for target in {
                t for t, sidecar in selected_items if _skill_repository(sidecar) == repo
            }:
                _persist_source_catalog(target, repo, tag, catalog)

    if updated:
        for skill_id, repo, target in updated:
            console.print(
                f"[skore.ok]^[/] updated [skore.skill]{skill_id}[/] "
                f"({repo}) -> [skore.path]{target}[/]"
            )
    elif considered_repos:
        console.print(
            f"All skills are up to date ({_format_sources(considered_repos)})."
        )
    else:
        console.print("All skills are up to date.")


@skills.command("remove")
@click.argument("ids", nargs=-1)
@_manage_agent_option
@_global_option
@click.option("--all", "all_", is_flag=True, help="Remove every installed skill.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts.")
def remove(ids, agent, global_, all_, yes) -> None:
    """Remove installed skills.

    Pass skill ids to remove, or ``--all`` to remove every installed skill.
    Scans every known agent by default; pass ``--agent`` to restrict the scan.
    Run ``skore skills list`` to see installed ids.
    """
    targets = _manage_targets(agent, global_=global_)

    if not all_ and not ids:
        if not is_non_interactive():
            selected = _interactive_manage_picker(
                _installed_skill_ids(targets),
                title="Select skills to remove.",
                sources=_installed_skill_sources(targets),
            )
            if not selected:
                console.print("Nothing selected.")
                return
            ids = selected
        else:
            raise click.UsageError(
                "Specify skill ids to remove or pass --all. "
                "Run `skore skills list` to discover ids."
            )

    to_remove = []
    for _, target in targets:
        if all_:
            for skill_dir, _ in _installed(target):
                to_remove.append(skill_dir)
        else:
            for skill_id in ids:
                skill_dir = target / skill_id
                if (skill_dir / SIDECAR).is_file():
                    to_remove.append(skill_dir)

    if not to_remove:
        console.print("Nothing to remove.")
        return

    if not yes:
        locations = ", ".join(str(skill_dir) for skill_dir in to_remove)
        console.print(f"Removing {locations}")
        if not click.confirm("Proceed?", default=True):
            return

    for skill_dir in to_remove:
        shutil.rmtree(skill_dir)
        console.print(f"[skore.ok]-[/] removed [skore.path]{skill_dir}[/]")

    for target in {skill_dir.parent for skill_dir in to_remove}:
        _prune_local_catalog(target)
