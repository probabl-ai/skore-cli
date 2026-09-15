"""Forward ``skore skills run`` to ``python -m skore_skills`` in the project env."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MISSING_MODULE = (
    "skore-skills is not installed in this project's interpreter.\n"
    "Install it in the project env (for example "
    "`pixi add --pypi skore-skills` or the agent extra)."
)


class MissingSkoreSkillsError(RuntimeError):
    """Raised when ``import skore_skills`` fails in the project interpreter."""


def project_python(root: Path) -> list[str]:
    """Return argv that runs the project interpreter.

    Pixi projects use ``pixi run`` (honoring ``PIXI_ENVIRONMENT``). Otherwise
    the current ``sys.executable`` is used.
    """
    pixi = shutil.which("pixi")
    if pixi is not None and (root / "pixi.toml").is_file():
        argv = [pixi, "run"]
        env_name = os.environ.get("PIXI_ENVIRONMENT")
        if env_name:
            argv.extend(["-e", env_name])
        argv.append("python")
        return argv
    return [sys.executable]


def probe_skore_skills(python: list[str], root: Path) -> bool:
    """Return True if ``skore_skills`` imports in that interpreter."""
    completed = subprocess.run(
        [*python, "-c", "import skore_skills"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def forward(root: Path, extra: list[str]) -> int:
    """Run ``python -m skore_skills`` with ``extra`` in ``root``.

    Parameters
    ----------
    root : pathlib.Path
        Project directory (pixi.toml detection and cwd).
    extra : list of str
        Arguments after ``skore skills run``.

    Returns
    -------
    int
        The subprocess exit code.

    Raises
    ------
    MissingSkoreSkillsError
        If the module cannot be imported in the project interpreter.
    """
    python = project_python(root)
    if not probe_skore_skills(python, root):
        raise MissingSkoreSkillsError
    completed = subprocess.run(
        [*python, "-m", "skore_skills", *extra],
        cwd=root,
        check=False,
    )
    return completed.returncode
