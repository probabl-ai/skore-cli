"""A2A client: drive the hub delegation task over a durable, streamed connection.

The relay no longer polls. It opens ONE task on the hub's A2A endpoint
(``POST /v1/a2a``, method ``message/stream``) and consumes a pushed SSE event
stream. When the agent defers tool calls, the hub emits an ``input-required``
event; the relay executes them locally (see :mod:`_handlers`) and posts the
results back with ``message/send`` -- the same open task resumes and streams the
next events. A dropped connection is transparently resumed with
``tasks/resubscribe`` from the last received event ``seq`` (the hub replays the
gap), so no events are lost and nothing is polled.

The SSE ``data:`` payload is the compact task-event dict produced by the hub task
manager; :func:`iter_sse` is factored out (pure) for unit testing.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from skore_cli.agent._harnesses import (
    API_KEY_ENV,
    WORKSPACE_HEADER,
    Credential,
    base_url,
)

logger = logging.getLogger("skore_cli.agent.mcp")

# Task states that end the stream (mirror hub.agent.tasks.TERMINAL_STATES).
TERMINAL_STATES = {"completed", "failed", "canceled"}


class A2AClientError(RuntimeError):
    """Raised when the hub A2A endpoint returns an error response."""


def _auth_headers(cred: Credential) -> dict[str, str]:
    """Return the real auth header for an HTTP call (not the ``{env:}`` form)."""
    if cred.kind == "api_key":
        return {"X-API-Key": os.environ.get(API_KEY_ENV, "")}
    if cred.kind == "bearer":
        return {"Authorization": f"Bearer {cred.token}"}
    return {}


def _error_message(status_code: int, body: bytes | str) -> str:
    """Extract an actionable message from an error response body."""
    text = body.decode() if isinstance(body, bytes) else body
    try:
        payload = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return f"hub returned HTTP {status_code}: {text[:300]}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return f"hub returned HTTP {status_code}."


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[dict]:
    """Parse an SSE line stream into event dicts (one per ``data:`` frame)."""
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                raw = "\n".join(data)
                data = []
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            yield json.loads("\n".join(data))
        except json.JSONDecodeError:
            return


class A2AClient:
    """Drive a single hub delegation task over a resumable SSE stream."""

    def __init__(
        self,
        *,
        hub_url: str,
        cred: Credential,
        hub_workspace: str | None,
        tools: list[dict],
        timeout: float = 600.0,
    ) -> None:
        self._base = base_url(hub_url)
        self._endpoint = self._base + "/a2a"
        self._cred = cred
        self._hub_workspace = hub_workspace
        self._tools = tools
        self._timeout = timeout
        # Live task state, tracked from the event stream.
        self.task_id = ""
        self.state = "submitted"
        self.result = ""
        self.error = ""
        self._last_seq = -1

    def _headers(self, *, sse: bool) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(_auth_headers(self._cred))
        if self._hub_workspace:
            headers[WORKSPACE_HEADER] = self._hub_workspace
        if sse:
            headers["Accept"] = "text/event-stream"
        return headers

    def _stream_payload(self, task_text: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/stream",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": task_text}],
                    "metadata": {"tools": self._tools},
                }
            },
        }

    def _resubscribe_payload(self) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/resubscribe",
            "params": {"id": self.task_id, "cursor": self._last_seq + 1},
        }

    def _track(self, event: dict) -> None:
        """Update the live task state from a streamed event."""
        seq = event.get("seq")
        if isinstance(seq, int):
            self._last_seq = max(self._last_seq, seq)
        if not self.task_id:
            task_id = event.get("task_id")
            if isinstance(task_id, str):
                self.task_id = task_id
        kind = event.get("kind")
        if kind == "status":
            self.state = event.get("state", self.state)
        elif kind == "result":
            self.state = "completed"
            self.result = event.get("text", "")
        elif kind == "error":
            self.state = "failed"
            self.error = event.get("message", "")

    @staticmethod
    def _is_terminal(event: dict) -> bool:
        if event.get("kind") in ("result", "error"):
            return True
        return event.get("kind") == "status" and event.get("state") in TERMINAL_STATES

    async def events(self, task_text: str) -> AsyncIterator[dict]:
        """Yield the task's events, auto-resuming a dropped stream.

        Starts the task with ``message/stream`` and yields each event. On a
        transport error (or a stream that closes before a terminal event), it
        reconnects with ``tasks/resubscribe`` from the last seen ``seq`` until a
        terminal event arrives.
        """
        import httpx

        payload = self._stream_payload(task_text)
        while True:
            try:
                async with (
                    httpx.AsyncClient(timeout=self._timeout) as client,
                    client.stream(
                        "POST",
                        self._endpoint,
                        json=payload,
                        headers=self._headers(sse=True),
                        follow_redirects=True,
                    ) as response,
                ):
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise A2AClientError(_error_message(response.status_code, body))
                    async for event in iter_sse(response.aiter_lines()):
                        self._track(event)
                        yield event
                        if self._is_terminal(event):
                            return
            except httpx.HTTPError as exc:
                if self.state in TERMINAL_STATES:
                    return
                logger.warning(
                    "a2a stream dropped (%s); resubscribing from seq %d",
                    exc,
                    self._last_seq + 1,
                )
            if self.state in TERMINAL_STATES:
                return
            if not self.task_id:
                # Never received the task id: nothing to resume against.
                raise A2AClientError(
                    "the hub connection failed before the task was created"
                )
            payload = self._resubscribe_payload()

    async def send_results(self, results: dict[str, str]) -> None:
        """Post the locally-executed tool results back to the waiting task."""
        import httpx

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "message": {
                    "taskId": self.task_id,
                    "role": "user",
                    "parts": [{"kind": "data", "data": {"tool_results": results}}],
                }
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._endpoint,
                json=payload,
                headers=self._headers(sse=False),
                follow_redirects=True,
            )
        if response.status_code >= 400:
            raise A2AClientError(_error_message(response.status_code, response.text))

    async def cancel(self) -> None:
        """Best-effort cancel of the task (e.g. when the MCP call is aborted)."""
        if not self.task_id:
            return
        import httpx

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/cancel",
            "params": {"id": self.task_id},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                await client.post(
                    self._endpoint,
                    json=payload,
                    headers=self._headers(sse=False),
                    follow_redirects=True,
                )
        except Exception:  # noqa: BLE001 - cancellation is best-effort
            logger.debug("a2a cancel failed for task %s", self.task_id)

    async def fetch_template(self, skill: str, path: str) -> str:
        """Fetch a raw skill template over the non-LLM data-plane channel."""
        import httpx

        url = f"{self._base}/skills/{skill}/template"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                url,
                params={"path": path},
                headers=self._headers(sse=False),
                follow_redirects=True,
            )
        if response.status_code >= 400:
            raise A2AClientError(_error_message(response.status_code, response.text))
        return response.text


@dataclass
class RelayConfig:
    """Resolved hub connection used to build per-task A2A clients."""

    default_workspace: Path
    hub_url: str
    hub_workspace: str | None
    cred: Credential

    def make_client(self) -> A2AClient:
        """Build an :class:`A2AClient` advertising the canonical local toolset."""
        from skore_cli.agent.mcp._jobs import CANONICAL_TOOLS

        return A2AClient(
            hub_url=self.hub_url,
            cred=self.cred,
            hub_workspace=self.hub_workspace,
            tools=CANONICAL_TOOLS,
        )
