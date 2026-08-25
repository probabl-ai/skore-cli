"""Read and write the project-local ``.skore`` agent configuration file."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from skore_cli._agents import normalize_harness_name

SKORE_FILENAME = ".skore"


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
        file_path = path / SKORE_FILENAME
        if not file_path.is_file():
            return None
        try:
            data = json.loads(file_path.read_text() or "{}")
        except json.JSONDecodeError:
            return None
        hub_url = data.get("hub_url")
        workspace = data.get("workspace")
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
        """Write this config to ``path/.skore`` and return the file path."""
        file_path = path / SKORE_FILENAME
        payload = {
            key: value for key, value in asdict(self).items() if value is not None
        }
        file_path.write_text(json.dumps(payload, indent=2) + "\n")
        return file_path


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
