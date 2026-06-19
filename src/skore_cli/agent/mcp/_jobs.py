"""Canonical delegation toolset + question/command normalization helpers.

The delegation *loop* now lives on the hub (see ``hub.agent.tasks``); the relay is
a thin A2A client (:mod:`_a2a_client`) that executes the agent's deferred tool
calls locally (:mod:`_handlers`). This module holds the harness-agnostic pieces
shared by that client:

* :data:`CANONICAL_TOOLS` -- the fixed tool set advertised to the hub agent (the
  hub mirrors them as its deferred external toolset);
* :func:`_normalize_questions` / :func:`_command_text` -- coerce an ``ask_user`` /
  ``run_bash`` call's arguments into the structured shapes the relay needs.
"""

from __future__ import annotations

import json
import re

# The reserved tool requiring explicit user approval before the relay runs it.
RUN_BASH_TOOL = "run_bash"
# Tools the relay executes locally (data plane); their bulk output never reaches
# the outer LLM, only a compact activity summary does.
RELAY_TOOLS = {"read_file", "write_file", "edit_file", "list_dir"}
MATERIALIZE_TOOL = "materialize_template"

# The reserved tool the hub agent calls to pause for a human decision (a skill
# gate). The relay routes it to the user instead of executing it.
ASK_USER_TOOL = "ask_user"

# A fixed, harness-agnostic tool set advertised to the hub agent. The outer LLM
# maps these to whatever native tools it has; the hub never sees (or depends on)
# a specific harness's tool naming.
CANONICAL_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a workspace file with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact text span in a workspace file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the entries of a workspace directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Run a shell command in the workspace and return output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": MATERIALIZE_TOOL,
            "description": (
                "Deliver a bundled skill template to the workspace VERBATIM. "
                "Prefer this over read_file/write_file when a skill instructs you "
                "to copy a template and substitute placeholders: the template body "
                "is fetched and written locally without passing through the "
                "transcript. `template_path` is the skill-relative template path "
                "(e.g. templates/experiment.py); `dest_path` is where to write it "
                "in the workspace; `substitutions` is a map of the exact "
                "placeholder text to its replacement (e.g. "
                '{"{{PKG_NAME}}": "digichem"}).'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "template_path": {"type": "string"},
                    "dest_path": {"type": "string"},
                    "substitutions": {"type": "object"},
                },
                "required": ["skill", "template_path", "dest_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ASK_USER_TOOL,
            "description": (
                "Ask the human user one or more questions at a skill gate and wait "
                "for THEIR answers (the relay surfaces them to the human; they are "
                "never answered by the outer model). Pass ONE entry per gate/"
                "decision in `questions` (never concatenate several gates into a "
                "single prompt). Set each `id` to the gate code (e.g. G-PKG-NAME), "
                "and fill `options`/`default` from the gate definition when known. "
                "Answers come back keyed by `id`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "prompt": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "multiple": {"type": "boolean"},
                                "default": {"type": "string"},
                            },
                            "required": ["prompt"],
                        },
                    }
                },
                "required": ["questions"],
            },
        },
    },
]


# A gate code like ``G-PKG-NAME`` used to identify a question deterministically.
_GATE_CODE = re.compile(r"\bG-[A-Z0-9][A-Z0-9-]*\b")
# Enumerated-list item markers, e.g. ``1.``/``2)`` at line start or inline.
_ENUM_MARKER = re.compile(r"(?:^|\s)\d+[.)]\s+")
# A gate code anchored at the start of a chunk (used as a fallback split point).
_GATE_CODE_SPLIT = re.compile(r"(?=\bG-[A-Z0-9][A-Z0-9-]*\b)")


def _coerce_question(raw: object, index: int) -> dict:
    """Coerce one question item into the full ``{id, prompt, options, ...}`` shape."""
    if isinstance(raw, str):
        raw = {"prompt": raw}
    if not isinstance(raw, dict):
        raw = {"prompt": str(raw)}
    prompt = ""
    for key in ("prompt", "question", "message", "text"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            prompt = value.strip()
            break
    raw_options = raw.get("options")
    options = [str(o) for o in raw_options] if isinstance(raw_options, list) else []
    qid = raw.get("id")
    if not isinstance(qid, str) or not qid.strip():
        match = _GATE_CODE.search(prompt)
        qid = match.group(0) if match else f"q{index + 1}"
    default = raw.get("default")
    return {
        "id": qid,
        "prompt": prompt or "The Skore agent needs your input to continue.",
        "options": options,
        "multiple": bool(raw.get("multiple", False)),
        "default": default if isinstance(default, str) else None,
    }


def _split_questions(text: str) -> list[dict]:
    """Fallback: split a single enumerated blob into separate questions.

    Used when the agent crams several gates into one free-text string instead of
    the structured ``questions`` array. Splits on numbered markers (``1.``/``2)``)
    and derives each id from a leading gate code when present.
    """
    text = text.strip()
    if not text:
        return [_coerce_question("", 0)]
    chunks = [c.strip() for c in _ENUM_MARKER.split(text) if c.strip()]
    if len(chunks) <= 1:
        # No numbered markers: fall back to splitting on gate codes if several
        # appear, otherwise treat the whole blob as one question.
        if len(_GATE_CODE.findall(text)) > 1:
            chunks = [c.strip() for c in _GATE_CODE_SPLIT.split(text) if c.strip()]
        else:
            return [_coerce_question(text, 0)]
    return [_coerce_question(chunk, i) for i, chunk in enumerate(chunks)]


def _command_text(args: object) -> str:
    """Pull the shell command out of a ``run_bash`` call's arguments."""
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return args.strip()
    if isinstance(args, dict):
        value = args.get("command")
        if isinstance(value, str):
            return value.strip()
    return ""


def _normalize_questions(args: object) -> list[dict]:
    """Normalize an ``ask_user`` call's arguments into a list of structured questions.

    Accepts the structured ``questions`` array, a legacy single ``question``/
    ``prompt`` string (split heuristically), or empty args.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return _split_questions(args)
    if isinstance(args, dict):
        questions = args.get("questions")
        if isinstance(questions, list) and questions:
            return [_coerce_question(item, i) for i, item in enumerate(questions)]
        for key in ("question", "prompt", "message", "text"):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return _split_questions(value)
    return [_coerce_question("", 0)]
