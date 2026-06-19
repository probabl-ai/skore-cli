"""Resolve the hub agent's deferred tool calls on the user's machine.

When the hub task streams an ``input-required`` event, it carries the agent's
deferred tool calls. This module classifies each call by its (canonical) name and
produces the result string fed back to the hub:

* data-plane (``read_file``/``write_file``/``edit_file``/``list_dir``/
  ``materialize_template``) -- executed locally via :mod:`_executor`; only a
  compact summary is surfaced to the outer LLM (``ctx.info``), never the bytes;
* ``run_bash`` -- the user approves it inline via MCP elicitation, then the relay
  runs it;
* ``ask_user`` -- a skill gate: the questions are put to the human inline via MCP
  elicitation (the outer model never answers them).

Elicitation is the only path for human decisions (the no-poll design assumes an
elicitation-capable host). If the host lacks elicitation, gate calls fail with a
clear, actionable error rather than silently letting the outer model decide.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field, create_model

from skore_cli.agent.mcp import _executor
from skore_cli.agent.mcp._jobs import (
    ASK_USER_TOOL,
    MATERIALIZE_TOOL,
    RELAY_TOOLS,
    RUN_BASH_TOOL,
    _command_text,
    _normalize_questions,
)

logger = logging.getLogger("skore_cli.agent.mcp")


class ElicitationUnsupportedError(RuntimeError):
    """Raised when a human gate needs elicitation but the host lacks it."""


class _ConfirmSchema(BaseModel):
    """Elicitation schema for inline shell-command approval."""

    approve: bool = Field(description="Approve running the shell command?")


def _sanitize_field_name(qid: str, index: int, used: set[str]) -> str:
    """Turn a question id (e.g. ``G-PKG-NAME``) into a unique valid field name."""
    safe = re.sub(r"\W", "_", qid).strip("_")
    if not safe or safe[0].isdigit():
        safe = f"q_{safe}".rstrip("_") or f"q{index + 1}"
    base = safe
    counter = 2
    while safe in used:
        safe = f"{base}_{counter}"
        counter += 1
    return safe


def _build_questions_form(
    questions: list[dict],
) -> tuple[type[BaseModel], dict[str, str]]:
    """Build an elicitation schema (one field per question) + a field->id map.

    Elicitation schemas only allow primitive field types, so every field is a
    ``str``: single-choice questions carry their ``options`` as a JSON-schema
    ``enum`` (rendered as a dropdown by capable hosts), and multi-select degrades
    to a free string whose description lists the options.
    """
    fields: dict[str, tuple[type, object]] = {}
    field_to_id: dict[str, str] = {}
    used: set[str] = set()
    for index, question in enumerate(questions):
        qid = question.get("id") or f"q{index + 1}"
        name = _sanitize_field_name(qid, index, used)
        used.add(name)
        field_to_id[name] = qid

        prompt = question.get("prompt") or "Your input is required to continue."
        options = question.get("options") or []
        multiple = bool(question.get("multiple"))
        default = question.get("default")

        description = prompt
        field_kwargs: dict[str, object] = {}
        if options and not multiple:
            field_kwargs["json_schema_extra"] = {"enum": list(options)}
        elif options and multiple:
            joined = ", ".join(str(o) for o in options)
            description = (
                f"{prompt} (choose one or more, comma-separated, from: {joined})"
            )
        field_kwargs["description"] = description

        if isinstance(default, str) and default:
            field_info = Field(default=default, **field_kwargs)
        else:
            field_info = Field(..., **field_kwargs)
        fields[name] = (str, field_info)

    model = create_model("SkoreQuestions", **fields)  # type: ignore[call-overload]
    return model, field_to_id


async def _answer_questions(ctx: object, args: object) -> str:
    """Put a skill gate's questions to the human inline; return JSON answers.

    Returns a JSON ``{question_id: answer}`` map. A decline/cancel yields an empty
    map (the hub agent may then apply its defaults). Raises
    :class:`ElicitationUnsupportedError` if the host cannot elicit.
    """
    questions = _normalize_questions(args)
    form, field_to_id = _build_questions_form(questions)
    count = len(questions)
    noun = "question" if count == 1 else "questions"
    try:
        result = await ctx.elicit(  # type: ignore[attr-defined]
            message=f"The Skore agent needs your input on {count} {noun} to continue.",
            schema=form,
        )
    except Exception as exc:  # noqa: BLE001 - host may not support elicitation
        raise ElicitationUnsupportedError(
            "this host does not support MCP elicitation, which is required to "
            "relay the Skore agent's skill-gate questions to you. Use an "
            "elicitation-capable MCP host."
        ) from exc
    action = getattr(result, "action", None)
    data = getattr(result, "data", None)
    if action == "accept" and data is not None:
        answers = {
            qid: str(value)
            for name, qid in field_to_id.items()
            if (value := getattr(data, name, None)) is not None
        }
        return json.dumps(answers)
    return json.dumps({})


async def _confirm_and_run(ctx: object, workspace, args: object) -> str:
    """Ask the user to approve a shell command inline, then run it if approved."""
    command = _command_text(args)
    if not command:
        return "no command provided"
    try:
        result = await ctx.elicit(  # type: ignore[attr-defined]
            message=f"The Skore agent wants to run: {command}", schema=_ConfirmSchema
        )
    except Exception:  # noqa: BLE001 - host may not support elicitation
        return "command declined (host cannot confirm shell commands)"
    action = getattr(result, "action", None)
    data = getattr(result, "data", None)
    approved = action == "accept" and bool(getattr(data, "approve", False))
    if not approved:
        return "command declined by the user"
    try:
        exec_result = await _executor.run_bash(workspace, command)
    except Exception as exc:  # noqa: BLE001 - surfaced to the hub as tool output
        message = f"run_bash failed: {exc}"
        await _info(ctx, message)
        return message
    await _info(ctx, exec_result.summary)
    return exec_result.output


async def _run_data_plane(ctx: object, client: object, workspace, name, args) -> str:
    """Execute a data-plane tool locally; emit a compact summary; return output."""
    parsed = args
    if isinstance(args, str):
        try:
            parsed = json.loads(args or "{}")
        except json.JSONDecodeError:
            parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    try:
        if name == "read_file":
            result = await _executor.read_file(workspace, parsed.get("path", ""))
        elif name == "write_file":
            result = await _executor.write_file(
                workspace, parsed.get("path", ""), parsed.get("content", "")
            )
        elif name == "edit_file":
            result = await _executor.edit_file(
                workspace,
                parsed.get("path", ""),
                parsed.get("old", ""),
                parsed.get("new", ""),
            )
        elif name == "list_dir":
            result = await _executor.list_dir(workspace, parsed.get("path", "."))
        elif name == MATERIALIZE_TOOL:
            template = await client.fetch_template(  # type: ignore[attr-defined]
                parsed.get("skill", ""), parsed.get("template_path", "")
            )
            result = _executor.materialize(
                workspace,
                parsed.get("dest_path", ""),
                template,
                parsed.get("substitutions"),
            )
        else:
            message = f"unknown tool {name!r}"
            await _info(ctx, message)
            return message
    except Exception as exc:  # noqa: BLE001 - surfaced to the hub as tool output
        message = f"{name} failed: {exc}"
        await _info(ctx, message)
        return message
    await _info(ctx, result.summary)
    return result.output


async def _info(ctx: object, message: str) -> None:
    """Best-effort progress line to the host (never fatal)."""
    try:
        await ctx.info(message)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - host may not support notifications
        logger.debug("ctx.info failed: %s", message)


async def resolve_tool_calls(
    ctx: object, client: object, workspace, tool_calls: list[dict]
) -> dict[str, str]:
    """Execute/relay each deferred tool call; return a ``{call_id: output}`` map."""
    results: dict[str, str] = {}
    for call in tool_calls:
        call_id = call.get("id", "")
        fn = call.get("function") or {}
        name = fn.get("name", "")
        args = fn.get("arguments", "")
        if name == ASK_USER_TOOL:
            results[call_id] = await _answer_questions(ctx, args)
        elif name == RUN_BASH_TOOL:
            results[call_id] = await _confirm_and_run(ctx, workspace, args)
        elif name in RELAY_TOOLS or name == MATERIALIZE_TOOL:
            results[call_id] = await _run_data_plane(ctx, client, workspace, name, args)
        else:
            message = f"unknown tool {name!r}"
            await _info(ctx, message)
            results[call_id] = message
    return results
