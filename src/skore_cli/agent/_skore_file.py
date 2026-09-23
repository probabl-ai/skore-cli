"""Read and write the project-local ``.skore`` agent configuration file."""

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from skore_cli._agents import normalize_harness_name

SKORE_FILENAME = ".skore"
_MANAGER_ORDER = ("pixi", "uv", "poetry", "hatch", "conda", "pip-venv")


@dataclass
class SkoreConfig:
    """Persisted Skore agent settings for a project."""

    hub_url: str
    workspace: str
    workspace_id: int
    api_key: str
    harness: str | None = None

    @classmethod
    def load(cls, path: Path) -> SkoreConfig | None:
        """Load ``.skore`` from ``path`` when present and valid."""
        data = _read_document(path / SKORE_FILENAME)
        if data is None:
            return None
        hub_url = data.get("hub_url")
        workspace = _hub_workspace_name(data)
        workspace_id = data.get("workspace_id")
        api_key = data.get("api_key")
        if not hub_url or not workspace or workspace_id is None or not api_key:
            return None
        harness = normalize_harness_name(data.get("harness"))
        return cls(
            hub_url=hub_url,
            workspace=workspace,
            workspace_id=int(workspace_id),
            api_key=api_key,
            harness=harness,
        )

    def save(self, path: Path) -> Path:
        """Merge this config into ``path/.skore`` and return the file path."""
        file_path = path / SKORE_FILENAME
        payload = _read_document(file_path) or {}
        for key, value in asdict(self).items():
            if value is None:
                if key == "harness":
                    payload.pop(key, None)
                continue
            if key == "workspace" and isinstance(payload.get("workspace"), dict):
                payload["workspace_name"] = value
                continue
            payload[key] = value
        _write_document(file_path, payload)
        return file_path


def _read_document(file_path: Path) -> dict[str, Any] | None:
    if not file_path.is_file():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_document(file_path: Path, payload: dict[str, Any]) -> None:
    file_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _hub_workspace_name(data: dict[str, Any]) -> str | None:
    raw = data.get("workspace")
    if isinstance(raw, str) and raw:
        return raw
    name = data.get("workspace_name")
    if isinstance(name, str) and name:
        return name
    return None


def visible_env_managers(root: Path) -> list[str]:
    """Return env-manager names visible from root manifests (skills order)."""
    evidence: dict[str, list[str]] = {}
    pixi_files = [
        name for name in ("pixi.toml", "pixi.lock") if (root / name).is_file()
    ]
    pyproject: dict[str, Any] = {}
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            pyproject = {}
    tools = pyproject.get("tool", {}) if isinstance(pyproject.get("tool"), dict) else {}
    if pixi_files:
        evidence["pixi"] = pixi_files
    elif "pixi" in tools:
        evidence["pixi"] = ["pyproject.toml:[tool.pixi]"]

    uv_bits: list[str] = []
    if (root / "uv.lock").is_file():
        uv_bits.append("uv.lock")
    if "uv" in tools:
        uv_bits.append("pyproject.toml:[tool.uv]")
    if uv_bits:
        evidence["uv"] = uv_bits

    poetry_bits: list[str] = []
    if (root / "poetry.lock").is_file():
        poetry_bits.append("poetry.lock")
    if "poetry" in tools:
        poetry_bits.append("pyproject.toml:[tool.poetry]")
    if poetry_bits:
        evidence["poetry"] = poetry_bits

    hatch_bits: list[str] = []
    if (root / "hatch.toml").is_file():
        hatch_bits.append("hatch.toml")
    hatch_tool = tools.get("hatch")
    if isinstance(hatch_tool, dict) and "envs" in hatch_tool:
        hatch_bits.append("pyproject.toml:[tool.hatch.envs]")
    if hatch_bits:
        evidence["hatch"] = hatch_bits

    conda_files = [
        name
        for name in ("environment.yml", "environment.yaml")
        if (root / name).is_file()
    ]
    if conda_files:
        evidence["conda"] = conda_files

    venv_dir = None
    for name in (".venv", "venv"):
        if (root / name).is_dir():
            venv_dir = name
            break
    if (root / "requirements.txt").is_file() and venv_dir is not None:
        evidence["pip-venv"] = ["requirements.txt", venv_dir]

    return [name for name in _MANAGER_ORDER if name in evidence]


def persist_workspace_env_manager(root: Path) -> None:
    """Set ``workspace.env_manager`` when exactly one manager is visible.

    Does not overwrite an existing ``env_manager``. Never sets ``env.managed``.
    """
    names = visible_env_managers(root)
    if len(names) != 1:
        return
    file_path = root / SKORE_FILENAME
    payload = _read_document(file_path) or {}
    section = payload.get("workspace")
    if isinstance(section, str) and section:
        payload.setdefault("workspace_name", section)
        section = {}
        payload["workspace"] = section
    if section is None:
        section = {}
        payload["workspace"] = section
    if not isinstance(section, dict):
        return
    if section.get("env_manager"):
        return
    section["env_manager"] = names[0]
    payload["workspace"] = section
    _write_document(file_path, payload)


def ensure_gitignore_entry(workspace: Path, entry: str = SKORE_FILENAME) -> None:
    """Append ``entry`` to the project ``.gitignore`` when missing."""
    gitignore = workspace / ".gitignore"
    if gitignore.is_file():
        lines = gitignore.read_text().splitlines()
        if any(line.strip() == entry for line in lines):
            return
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(entry)
        gitignore.write_text("\n".join(lines) + "\n")
        return
    gitignore.write_text(f"{entry}\n")
