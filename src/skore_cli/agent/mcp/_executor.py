"""Local, workspace-confined execution of the relay's data-plane tools.

The hub agent's file/command tool calls are executed here (in the user's
workspace) instead of being relayed to the outer LLM. Each operation returns an
:class:`ExecResult` carrying:

* ``output`` -- the full result fed back to the hub agent as the tool result
  (e.g. a file's content), so the agent keeps reasoning with real data;
* ``summary`` -- a compact one-line description surfaced to the outer LLM as
  ``activity`` (e.g. ``wrote tests/test_x.py (42 lines)``), so bulk bytes never
  enter the outer model's context.

All paths are confined to the workspace: absolute paths and ``..`` escapes are
rejected. Blocking file IO runs in a thread and shell commands run as a
subprocess, so the asyncio event loop driving the jobs is never blocked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

# Cap how much command output we feed back to the hub (keeps hub input bounded);
# the middle of very long output is elided.
_MAX_OUTPUT_CHARS = 20_000
# Default wall-clock budget for a shell command.
_DEFAULT_TIMEOUT = 600.0


class ExecError(RuntimeError):
    """Raised when a data-plane operation cannot be performed safely."""


@dataclass
class ExecResult:
    """The outcome of one data-plane operation."""

    output: str
    summary: str


def _safe_path(workspace: Path, path: str) -> Path:
    """Resolve ``path`` strictly inside ``workspace``.

    Rejects absolute paths and any ``..`` traversal that would escape the
    workspace root.
    """
    if not isinstance(path, str) or not path.strip():
        raise ExecError("a non-empty path is required")
    candidate = Path(path)
    if candidate.is_absolute():
        raise ExecError(f"absolute paths are not allowed: {path!r}")
    root = workspace.resolve()
    target = (root / candidate).resolve()
    if target != root and root not in target.parents:
        raise ExecError(f"path escapes the workspace: {path!r}")
    return target


def _rel(workspace: Path, target: Path) -> str:
    """Best-effort workspace-relative display path."""
    try:
        return target.relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return target.as_posix()


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """Elide the middle of an over-long string, keeping head and tail."""
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    elided = len(text) - limit
    return f"{text[:head]}\n... [{elided} chars elided] ...\n{text[-tail:]}"


def _read_file(workspace: Path, path: str) -> ExecResult:
    target = _safe_path(workspace, path)
    if not target.is_file():
        raise ExecError(f"file not found: {path!r}")
    content = target.read_text()
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return ExecResult(
        output=content,
        summary=f"read {_rel(workspace, target)} ({lines} lines)",
    )


def _write_file(workspace: Path, path: str, content: str) -> ExecResult:
    target = _safe_path(workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else str(content)
    target.write_text(text)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    summary = f"wrote {_rel(workspace, target)} ({lines} lines)"
    return ExecResult(output=summary, summary=summary)


def _edit_file(workspace: Path, path: str, old: str, new: str) -> ExecResult:
    target = _safe_path(workspace, path)
    if not target.is_file():
        raise ExecError(f"file not found: {path!r}")
    if not isinstance(old, str) or old == "":
        raise ExecError("`old` must be a non-empty string")
    content = target.read_text()
    occurrences = content.count(old)
    if occurrences == 0:
        raise ExecError(f"`old` text not found in {path!r}")
    if occurrences > 1:
        raise ExecError(
            f"`old` text is ambiguous in {path!r} ({occurrences} matches); "
            "include more surrounding context to make it unique"
        )
    updated = content.replace(old, new if isinstance(new, str) else str(new), 1)
    target.write_text(updated)
    summary = f"edited {_rel(workspace, target)}"
    return ExecResult(output=summary, summary=summary)


def _list_dir(workspace: Path, path: str = ".") -> ExecResult:
    target = _safe_path(workspace, path or ".")
    if not target.is_dir():
        raise ExecError(f"directory not found: {path!r}")
    entries = [
        child.name + ("/" if child.is_dir() else "")
        for child in sorted(target.iterdir())
    ]
    listing = "\n".join(entries)
    return ExecResult(
        output=listing,
        summary=f"listed {_rel(workspace, target)} ({len(entries)} entries)",
    )


async def read_file(workspace: Path, path: str) -> ExecResult:
    """Read a workspace text file."""
    return await asyncio.to_thread(_read_file, workspace, path)


async def write_file(workspace: Path, path: str, content: str) -> ExecResult:
    """Create or overwrite a workspace file."""
    return await asyncio.to_thread(_write_file, workspace, path, content)


async def edit_file(workspace: Path, path: str, old: str, new: str) -> ExecResult:
    """Replace an exact, unique text span in a workspace file."""
    return await asyncio.to_thread(_edit_file, workspace, path, old, new)


async def list_dir(workspace: Path, path: str = ".") -> ExecResult:
    """List a workspace directory."""
    return await asyncio.to_thread(_list_dir, workspace, path)


async def run_bash(
    workspace: Path, command: str, timeout: float = _DEFAULT_TIMEOUT
) -> ExecResult:
    """Run a shell command in the workspace, returning exit code + output."""
    if not isinstance(command, str) or not command.strip():
        raise ExecError("a non-empty command is required")
    root = workspace.resolve()
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ExecError(
            f"command timed out after {timeout:.0f}s: {command!r}"
        ) from None
    text = (stdout or b"").decode("utf-8", errors="replace")
    code = proc.returncode if proc.returncode is not None else -1
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    output = f"exit code: {code}\n{_truncate(text)}"
    return ExecResult(
        output=output,
        summary=f"ran `{command}` -> exit {code} ({lines} lines)",
    )


def materialize(
    workspace: Path, dest_path: str, template_text: str, substitutions: object
) -> ExecResult:
    """Write a fetched template to ``dest_path`` after literal substitutions.

    ``substitutions`` is a ``{find: replace}`` map applied as plain string
    replacements (the agent supplies the placeholders it knows from the skill),
    so the large template body never passes through any LLM.
    """
    text = template_text
    if isinstance(substitutions, dict):
        for find, replace in substitutions.items():
            text = text.replace(str(find), str(replace))
    target = _safe_path(workspace, dest_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    summary = f"materialized {_rel(workspace, target)} ({lines} lines)"
    return ExecResult(output=summary, summary=summary)
