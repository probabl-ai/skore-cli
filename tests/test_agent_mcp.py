"""Tests for the ``skore agent mcp`` delegation relay (no-poll, A2A-backed).

The relay opens ONE durable task on the hub's A2A endpoint and consumes a pushed
SSE event stream; it executes the agent's deferred tool calls locally and posts
results back, exposing a single blocking ``skore_ml_run`` tool to the outer LLM.
Tests use fakes (no network): a fake A2A client for the relay loop, a fake MCP
context for elicitation, and a fake ``httpx`` for the client's reconnect logic.
The MCP-SDK-dependent server build is guarded with ``importorskip``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
import rich_click as click
from click.testing import CliRunner

from skore_cli.agent._harnesses import Credential
from skore_cli.agent.mcp import _a2a_client, _handlers, _hosts, _jobs
from skore_cli.agent.mcp import _commands as mcp_commands
from skore_cli.agent.mcp._a2a_client import RelayConfig
from skore_cli.agent.mcp._commands import (
    _resolve_serve_workspace,
    install,
    serve,
    status,
)
from skore_cli.agent.mcp._jobs import ASK_USER_TOOL, CANONICAL_TOOLS

# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


class _FakeContext:
    """A minimal MCP Context fake exposing info(), report_progress() and elicit()."""

    def __init__(
        self,
        *,
        action: str = "accept",
        values: dict[str, str] | None = None,
        approve: bool = True,
        raise_on_elicit: bool = False,
    ) -> None:
        self.action = action
        self.values = values or {}
        self.approve = approve
        self.raise_on_elicit = raise_on_elicit
        self.infos: list[str] = []
        self.elicited: list[str] = []

    async def info(self, message: str) -> None:
        self.infos.append(message)

    async def report_progress(self, **_kwargs) -> None:
        return None

    async def elicit(self, message: str, schema):
        self.elicited.append(message)
        if self.raise_on_elicit:
            raise RuntimeError("host does not support elicitation")
        if self.action != "accept":
            return SimpleNamespace(action=self.action, data=None)
        fields = list(schema.model_fields)
        if fields == ["approve"]:
            return SimpleNamespace(
                action="accept", data=SimpleNamespace(approve=self.approve)
            )
        data = {name: self.values.get(name, "x") for name in fields}
        return SimpleNamespace(action="accept", data=SimpleNamespace(**data))


class _FakeClient:
    """A scripted A2A client yielding fixed events; records posted results."""

    def __init__(self, events: list[dict], *, template: str = "") -> None:
        self._events = events
        self.sent: list[dict] = []
        self.cancelled = False
        self.task_id = "task_fake"
        self.state = "submitted"
        self.result = ""
        self.error = ""
        self.template = template
        self.template_calls: list[tuple[str, str]] = []

    async def events(self, task_text: str):
        for event in self._events:
            kind = event.get("kind")
            if kind == "status":
                self.state = event.get("state", self.state)
            elif kind == "result":
                self.state = "completed"
                self.result = event.get("text", "")
            elif kind == "error":
                self.state = "failed"
                self.error = event.get("message", "")
            yield event

    async def send_results(self, results: dict[str, str]) -> None:
        self.sent.append(results)

    async def cancel(self) -> None:
        self.cancelled = True

    async def fetch_template(self, skill: str, path: str) -> str:
        self.template_calls.append((skill, path))
        return self.template


def _tool_call(call_id, name, args):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _config(tmp_path):
    return RelayConfig(
        default_workspace=tmp_path,
        hub_url="http://hub.test",
        hub_workspace=None,
        cred=Credential("api_key"),
    )


# --------------------------------------------------------------------------- #
# client transport: auth, headers, payloads
# --------------------------------------------------------------------------- #


def test_auth_headers_api_key(monkeypatch):
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")
    assert _a2a_client._auth_headers(Credential("api_key")) == {
        "X-API-Key": "uid:secret"
    }


def test_auth_headers_bearer():
    assert _a2a_client._auth_headers(Credential("bearer", "tok")) == {
        "Authorization": "Bearer tok"
    }


def test_auth_headers_none():
    assert _a2a_client._auth_headers(Credential("none")) == {}


def test_client_headers_include_workspace_and_accept():
    client = _a2a_client.A2AClient(
        hub_url="http://hub.test",
        cred=Credential("bearer", "tok"),
        hub_workspace="ws-1",
        tools=[],
    )
    sse = client._headers(sse=True)
    assert sse["X-Skore-Workspace"] == "ws-1"
    assert sse["Authorization"] == "Bearer tok"
    assert sse["Accept"] == "text/event-stream"
    # The non-streaming POST omits the SSE Accept header.
    assert "Accept" not in client._headers(sse=False)


def test_endpoint_targets_v1_a2a():
    client = _a2a_client.A2AClient(
        hub_url="http://hub.test/",
        cred=Credential("none"),
        hub_workspace=None,
        tools=[],
    )
    assert client._endpoint == "http://hub.test/v1/a2a"


def test_stream_payload_carries_task_and_tools():
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    client = _a2a_client.A2AClient(
        hub_url="http://hub.test",
        cred=Credential("none"),
        hub_workspace=None,
        tools=tools,
    )
    payload = client._stream_payload("explore the data")
    assert payload["method"] == "message/stream"
    message = payload["params"]["message"]
    assert message["parts"][0]["text"] == "explore the data"
    assert message["metadata"]["tools"] == tools


def test_resubscribe_payload_resumes_after_last_seq():
    client = _a2a_client.A2AClient(
        hub_url="http://hub.test", cred=Credential("none"), hub_workspace=None, tools=[]
    )
    client.task_id = "task_1"
    client._last_seq = 4
    payload = client._resubscribe_payload()
    assert payload["method"] == "tasks/resubscribe"
    assert payload["params"] == {"id": "task_1", "cursor": 5}


def test_track_updates_state_task_id_and_seq():
    client = _a2a_client.A2AClient(
        hub_url="http://hub.test", cred=Credential("none"), hub_workspace=None, tools=[]
    )
    client._track({"seq": 0, "task_id": "task_9", "kind": "status", "state": "working"})
    assert client.task_id == "task_9"
    assert client.state == "working"
    assert client._last_seq == 0
    client._track({"seq": 3, "kind": "result", "text": "done"})
    assert client.state == "completed"
    assert client.result == "done"
    assert client._last_seq == 3


def test_is_terminal_detects_end_events():
    assert _a2a_client.A2AClient._is_terminal({"kind": "result"})
    assert _a2a_client.A2AClient._is_terminal({"kind": "error"})
    assert _a2a_client.A2AClient._is_terminal({"kind": "status", "state": "canceled"})
    assert not _a2a_client.A2AClient._is_terminal(
        {"kind": "status", "state": "working"}
    )
    assert not _a2a_client.A2AClient._is_terminal({"kind": "activity", "text": "x"})


# --------------------------------------------------------------------------- #
# SSE parsing
# --------------------------------------------------------------------------- #


def test_iter_sse_parses_frames():
    async def _lines():
        for line in [
            "id: 0",
            'data: {"seq": 0, "kind": "status", "state": "working"}',
            "",
            ": keep-alive comment",
            "id: 1",
            'data: {"seq": 1, "kind": "result", "text": "hi"}',
            "",
        ]:
            yield line

    async def _collect():
        return [event async for event in _a2a_client.iter_sse(_lines())]

    events = asyncio.run(_collect())
    assert [e["kind"] for e in events] == ["status", "result"]
    assert events[1]["text"] == "hi"


# --------------------------------------------------------------------------- #
# client events(): reconnect via resubscribe on a dropped stream
# --------------------------------------------------------------------------- #


class _FakeStream:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aread(self):
        return b"{}"

    async def aiter_lines(self):
        for line in self._lines:
            if isinstance(line, Exception):
                raise line
            yield line


def _sse(seq, payload):
    return [f"id: {seq}", f"data: {json.dumps(payload)}", ""]


def test_events_resubscribes_after_drop(monkeypatch):
    import httpx

    # First connection: emits seq 0/1 then drops mid-stream. The reconnect must
    # resume from seq 2 and complete.
    scripts = [
        [
            *_sse(
                0, {"seq": 0, "task_id": "task_z", "kind": "status", "state": "working"}
            ),
            *_sse(1, {"seq": 1, "kind": "activity", "text": "step"}),
            httpx.ReadError("connection reset"),
        ],
        [*_sse(2, {"seq": 2, "kind": "result", "text": "finished"})],
    ]
    seen_payloads: list[dict] = []

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, *, json=None, **k):
            seen_payloads.append(json)
            return _FakeStream(scripts.pop(0))

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = _a2a_client.A2AClient(
        hub_url="http://hub.test", cred=Credential("none"), hub_workspace=None, tools=[]
    )

    async def _collect():
        return [event async for event in client.events("do ml")]

    events = asyncio.run(_collect())
    assert [e["kind"] for e in events] == ["status", "activity", "result"]
    assert client.result == "finished"
    # The second request was a resubscribe resuming from the last seen seq + 1.
    assert seen_payloads[0]["method"] == "message/stream"
    assert seen_payloads[1]["method"] == "tasks/resubscribe"
    assert seen_payloads[1]["params"] == {"id": "task_z", "cursor": 2}


def test_events_raises_on_http_error(monkeypatch):
    import httpx

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, **k):
            return _FakeStream([], status=403)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = _a2a_client.A2AClient(
        hub_url="http://hub.test", cred=Credential("none"), hub_workspace=None, tools=[]
    )

    async def _collect():
        return [event async for event in client.events("x")]

    with pytest.raises(_a2a_client.A2AClientError):
        asyncio.run(_collect())


# --------------------------------------------------------------------------- #
# canonical toolset (shared schema)
# --------------------------------------------------------------------------- #


def test_canonical_tools_include_ask_user():
    names = [t["function"]["name"] for t in CANONICAL_TOOLS]
    assert ASK_USER_TOOL in names
    assert {"read_file", "write_file", "run_bash", "materialize_template"} <= set(names)


def test_ask_user_tool_advertises_questions_array():
    ask = next(t for t in CANONICAL_TOOLS if t["function"]["name"] == ASK_USER_TOOL)
    params = ask["function"]["parameters"]
    assert params["required"] == ["questions"]
    questions = params["properties"]["questions"]
    assert questions["type"] == "array"
    item_props = questions["items"]["properties"]
    assert {"id", "prompt", "options", "multiple", "default"} <= set(item_props)


def test_normalize_questions_structured_passthrough():
    args = {
        "questions": [
            {"id": "G-A", "prompt": "Pick env", "options": ["pixi", "uv"]},
            {"prompt": "Tabular lib?", "default": "pandas"},
        ]
    }
    qs = _jobs._normalize_questions(args)
    assert [q["id"] for q in qs] == ["G-A", "q2"]
    assert qs[0]["options"] == ["pixi", "uv"]
    assert qs[1]["prompt"] == "Tabular lib?"
    assert qs[1]["default"] == "pandas"


def test_normalize_questions_legacy_single_string():
    qs = _jobs._normalize_questions('{"question": "Which CV?"}')
    assert len(qs) == 1
    assert qs[0]["prompt"] == "Which CV?"
    assert _jobs._normalize_questions("{}")[0]["prompt"]


def test_normalize_questions_splits_enumerated_blob():
    text = "1. G-PKG-NAME what package name? 2. G-ENV-MGR which environment manager?"
    qs = _jobs._normalize_questions({"question": text})
    assert [q["id"] for q in qs] == ["G-PKG-NAME", "G-ENV-MGR"]


# --------------------------------------------------------------------------- #
# elicitation form
# --------------------------------------------------------------------------- #


def test_build_questions_form_options_default_and_sanitized_ids():
    questions = [
        {
            "id": "G-PKG-NAME",
            "prompt": "Package name?",
            "options": [],
            "multiple": False,
            "default": "digichem",
        },
        {
            "id": "G-TABULAR",
            "prompt": "Tabular lib?",
            "options": ["pandas", "polars"],
            "multiple": False,
            "default": None,
        },
        {
            "id": "G-EXTRAS",
            "prompt": "Extras?",
            "options": ["a", "b", "c"],
            "multiple": True,
            "default": None,
        },
    ]
    model, field_to_id = _handlers._build_questions_form(questions)
    schema = model.model_json_schema()
    props = schema["properties"]

    assert field_to_id == {
        "G_PKG_NAME": "G-PKG-NAME",
        "G_TABULAR": "G-TABULAR",
        "G_EXTRAS": "G-EXTRAS",
    }
    assert props["G_PKG_NAME"]["default"] == "digichem"
    assert "G_PKG_NAME" not in schema.get("required", [])
    assert props["G_TABULAR"]["enum"] == ["pandas", "polars"]
    assert "G_TABULAR" in schema["required"]
    assert props["G_EXTRAS"]["type"] == "string"
    assert "enum" not in props["G_EXTRAS"]
    assert "comma-separated" in props["G_EXTRAS"]["description"]


# --------------------------------------------------------------------------- #
# tool-call resolution (data plane + gates)
# --------------------------------------------------------------------------- #


def test_resolve_write_file_executes_and_summarizes(tmp_path):
    ctx = _FakeContext()
    client = _FakeClient([])
    calls = [_tool_call("c1", "write_file", {"path": "out/foo.txt", "content": "hi\n"})]
    results = asyncio.run(_handlers.resolve_tool_calls(ctx, client, tmp_path, calls))
    assert (tmp_path / "out" / "foo.txt").read_text() == "hi\n"
    assert "wrote out/foo.txt" in results["c1"]
    assert any("wrote out/foo.txt" in m for m in ctx.infos)


def test_resolve_read_file_returns_content(tmp_path):
    (tmp_path / "data.txt").write_text("hello\nworld\n")
    ctx = _FakeContext()
    calls = [_tool_call("c1", "read_file", {"path": "data.txt"})]
    results = asyncio.run(
        _handlers.resolve_tool_calls(ctx, _FakeClient([]), tmp_path, calls)
    )
    assert results["c1"] == "hello\nworld\n"


def test_resolve_read_file_error_is_surfaced(tmp_path):
    ctx = _FakeContext()
    calls = [_tool_call("c1", "read_file", {"path": "missing.txt"})]
    results = asyncio.run(
        _handlers.resolve_tool_calls(ctx, _FakeClient([]), tmp_path, calls)
    )
    assert "read_file failed" in results["c1"]


def test_resolve_materialize_fetches_template_and_substitutes(tmp_path):
    ctx = _FakeContext()
    client = _FakeClient([], template="name = '<NAME>'\n")
    calls = [
        _tool_call(
            "m1",
            "materialize_template",
            {
                "skill": "demo",
                "template_path": "templates/exp.py",
                "dest_path": "exp.py",
                "substitutions": {"<NAME>": "churn"},
            },
        )
    ]
    results = asyncio.run(_handlers.resolve_tool_calls(ctx, client, tmp_path, calls))
    assert (tmp_path / "exp.py").read_text() == "name = 'churn'\n"
    assert client.template_calls == [("demo", "templates/exp.py")]
    assert "materialized exp.py" in results["m1"]


def test_resolve_run_bash_approve_runs(tmp_path):
    ctx = _FakeContext(approve=True)
    calls = [_tool_call("c1", "run_bash", {"command": "echo hi"})]
    results = asyncio.run(
        _handlers.resolve_tool_calls(ctx, _FakeClient([]), tmp_path, calls)
    )
    assert "exit code: 0" in results["c1"]
    assert "hi" in results["c1"]
    assert ctx.elicited  # the user was asked to confirm


def test_resolve_run_bash_decline_does_not_run(tmp_path):
    ctx = _FakeContext(approve=False)
    calls = [_tool_call("c1", "run_bash", {"command": "rm -rf /"})]
    results = asyncio.run(
        _handlers.resolve_tool_calls(ctx, _FakeClient([]), tmp_path, calls)
    )
    assert "declined" in results["c1"]


def test_resolve_ask_user_elicits_and_keys_answers(tmp_path):
    ctx = _FakeContext(action="accept", values={"G_TGT": "churn"})
    calls = [
        _tool_call(
            "a1", ASK_USER_TOOL, {"questions": [{"id": "G-TGT", "prompt": "Target?"}]}
        )
    ]
    results = asyncio.run(
        _handlers.resolve_tool_calls(ctx, _FakeClient([]), tmp_path, calls)
    )
    assert json.loads(results["a1"]) == {"G-TGT": "churn"}
    assert ctx.elicited


def test_resolve_ask_user_decline_returns_empty(tmp_path):
    ctx = _FakeContext(action="decline")
    calls = [
        _tool_call(
            "a1", ASK_USER_TOOL, {"questions": [{"id": "G-TGT", "prompt": "Target?"}]}
        )
    ]
    results = asyncio.run(
        _handlers.resolve_tool_calls(ctx, _FakeClient([]), tmp_path, calls)
    )
    assert json.loads(results["a1"]) == {}


def test_resolve_ask_user_unsupported_elicitation_raises(tmp_path):
    ctx = _FakeContext(raise_on_elicit=True)
    calls = [
        _tool_call(
            "a1", ASK_USER_TOOL, {"questions": [{"id": "G-TGT", "prompt": "Target?"}]}
        )
    ]
    with pytest.raises(_handlers.ElicitationUnsupportedError):
        asyncio.run(_handlers.resolve_tool_calls(ctx, _FakeClient([]), tmp_path, calls))


# --------------------------------------------------------------------------- #
# drive_task: the blocking relay loop
# --------------------------------------------------------------------------- #


def test_drive_task_executes_tools_and_returns_result(tmp_path):
    from skore_cli.agent.mcp._server import drive_task

    events = [
        {"seq": 0, "task_id": "t", "kind": "status", "state": "working"},
        {
            "seq": 1,
            "kind": "input-required",
            "tool_calls": [
                _tool_call("w1", "write_file", {"path": "a.txt", "content": "x"}),
                _tool_call(
                    "a1", ASK_USER_TOOL, {"questions": [{"id": "G-A", "prompt": "?"}]}
                ),
            ],
        },
        {"seq": 2, "kind": "activity", "text": "scaffolding"},
        {"seq": 3, "kind": "result", "text": "All done."},
    ]
    client = _FakeClient(events)
    ctx = _FakeContext(values={"G_A": "pick"})

    result = asyncio.run(drive_task(ctx, client, "build a model", tmp_path))
    assert result == "All done."
    # The write executed locally; the gate was elicited; both fed back to the hub.
    assert (tmp_path / "a.txt").read_text() == "x"
    assert client.sent == [{"w1": "wrote a.txt (1 lines)", "a1": '{"G-A": "pick"}'}]
    assert any("scaffolding" in m for m in ctx.infos)


def test_drive_task_surfaces_error(tmp_path):
    from skore_cli.agent.mcp._server import drive_task

    events = [
        {"seq": 0, "kind": "status", "state": "working"},
        {"seq": 1, "kind": "error", "message": "workspace not found"},
    ]
    result = asyncio.run(drive_task(_FakeContext(), _FakeClient(events), "x", tmp_path))
    assert "workspace not found" in result


def test_drive_task_unsupported_elicitation_cancels(tmp_path):
    from skore_cli.agent.mcp._server import drive_task

    events = [
        {"seq": 0, "kind": "status", "state": "working"},
        {
            "seq": 1,
            "kind": "input-required",
            "tool_calls": [
                _tool_call(
                    "a1", ASK_USER_TOOL, {"questions": [{"id": "G-A", "prompt": "?"}]}
                )
            ],
        },
    ]
    client = _FakeClient(events)
    ctx = _FakeContext(raise_on_elicit=True)
    result = asyncio.run(drive_task(ctx, client, "x", tmp_path))
    assert "does not support MCP elicitation" in result
    assert client.cancelled


# --------------------------------------------------------------------------- #
# host writers
# --------------------------------------------------------------------------- #


def test_serve_args_embeds_hub_url_and_workspace(tmp_path):
    ctx = _hosts.InstallContext(
        workspace=tmp_path, hub_url="http://hub.test", hub_workspace="ws-1"
    )
    assert _hosts._serve_args(ctx) == [
        "agent",
        "mcp",
        "serve",
        "--hub-url",
        "http://hub.test",
        "--hub-workspace",
        "ws-1",
    ]


def test_install_cursor_writes_mcp_json(tmp_path):
    _hosts.HOSTS["cursor"].configure(_hosts.InstallContext(workspace=tmp_path))
    config = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    server = config["mcpServers"]["skore-ml"]
    assert server["command"] == "skore"
    assert server["args"] == ["agent", "mcp", "serve"]


def test_install_cursor_embeds_flags(tmp_path):
    ctx = _hosts.InstallContext(
        workspace=tmp_path, hub_url="http://hub.test", hub_workspace="ws-1"
    )
    _hosts.HOSTS["cursor"].configure(ctx)
    config = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    args = config["mcpServers"]["skore-ml"]["args"]
    assert args[-4:] == ["--hub-url", "http://hub.test", "--hub-workspace", "ws-1"]


def test_install_claude_code_writes_mcp_json(tmp_path):
    _hosts.HOSTS["claude-code"].configure(_hosts.InstallContext(workspace=tmp_path))
    config = json.loads((tmp_path / ".mcp.json").read_text())
    assert config["mcpServers"]["skore-ml"]["command"] == "skore"


def test_install_opencode_writes_mcp_block(tmp_path):
    _hosts.HOSTS["opencode"].configure(_hosts.InstallContext(workspace=tmp_path))
    config = json.loads((tmp_path / "opencode.json").read_text())
    entry = config["mcp"]["skore-ml"]
    assert entry["type"] == "local"
    assert entry["command"] == ["skore", "agent", "mcp", "serve"]
    assert entry["enabled"] is True


def test_install_codex_appends_idempotent_block(tmp_path, monkeypatch):
    monkeypatch.setattr(_hosts.Path, "home", classmethod(lambda cls: tmp_path))
    _hosts.HOSTS["codex"].configure(_hosts.InstallContext(workspace=tmp_path))
    config_path = tmp_path / ".codex" / "config.toml"
    text = config_path.read_text()
    assert "[mcp_servers.skore-ml]" in text
    assert 'command = "skore"' in text
    _hosts.HOSTS["codex"].configure(_hosts.InstallContext(workspace=tmp_path))
    assert config_path.read_text().count("[mcp_servers.skore-ml]") == 1


def test_install_generic_prints_command(tmp_path, monkeypatch):
    printed: list[str] = []
    monkeypatch.setattr(
        _hosts,
        "console",
        SimpleNamespace(print=lambda *a, **k: printed.append(" ".join(map(str, a)))),
    )
    _hosts.HOSTS["generic"].configure(_hosts.InstallContext(workspace=tmp_path))
    assert any("skore agent mcp serve" in line for line in printed)


def test_install_backs_up_invalid_json(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text("{ not json")
    _hosts.HOSTS["cursor"].configure(_hosts.InstallContext(workspace=tmp_path))
    assert (tmp_path / ".cursor" / "mcp.json.bak").is_file()
    config = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    assert config["mcpServers"]["skore-ml"]


# --------------------------------------------------------------------------- #
# install command (CliRunner)
# --------------------------------------------------------------------------- #


def test_install_command_writes_config(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_commands, "resolve_credential", lambda: Credential("none"))
    monkeypatch.setattr(mcp_commands, "resolve_hub_uri", lambda *_: "http://hub.test")
    result = CliRunner().invoke(
        install, ["--host", "cursor", "--workspace", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".cursor" / "mcp.json").is_file()


def test_install_command_nonexistent_workspace_errors(tmp_path):
    missing = tmp_path / "nope"
    result = CliRunner().invoke(
        install, ["--host", "cursor", "--workspace", str(missing)]
    )
    assert result.exit_code != 0
    assert "workspace does not exist" in result.output


def test_install_command_bearer_embeds_workspace_and_url(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mcp_commands, "resolve_credential", lambda: Credential("bearer", "tok")
    )
    monkeypatch.setattr(mcp_commands, "resolve_hub_uri", lambda *_: "http://hub.test")
    result = CliRunner().invoke(
        install,
        ["--host", "cursor", "--workspace", str(tmp_path), "--hub-workspace", "ws-1"],
    )
    assert result.exit_code == 0, result.output
    args = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())["mcpServers"][
        "skore-ml"
    ]["args"]
    assert args == [
        "agent",
        "mcp",
        "serve",
        "--hub-url",
        "http://hub.test",
        "--hub-workspace",
        "ws-1",
    ]


def test_install_command_api_key_ignores_hub_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mcp_commands, "resolve_credential", lambda: Credential("api_key")
    )
    monkeypatch.setattr(mcp_commands, "resolve_hub_uri", lambda *_: "http://hub.test")
    result = CliRunner().invoke(
        install,
        ["--host", "cursor", "--workspace", str(tmp_path), "--hub-workspace", "ws-1"],
    )
    assert result.exit_code == 0, result.output
    args = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())["mcpServers"][
        "skore-ml"
    ]["args"]
    assert args == ["agent", "mcp", "serve", "--hub-url", "http://hub.test"]


# --------------------------------------------------------------------------- #
# installed() detection + status command
# --------------------------------------------------------------------------- #


def test_installed_reports_registered_host(tmp_path, monkeypatch):
    # Point codex's global config at the temp dir so nothing on disk leaks in.
    monkeypatch.setattr(_hosts.Path, "home", classmethod(lambda cls: tmp_path))
    ctx = _hosts.InstallContext(
        workspace=tmp_path, hub_url="http://hub.test", hub_workspace="ws-1"
    )
    _hosts.HOSTS["cursor"].configure(ctx)

    by_name = {row.name: row for row in _hosts.installed(tmp_path)}
    cursor = by_name["cursor"]
    assert cursor.present is True
    assert cursor.serve_args[-4:] == [
        "--hub-url",
        "http://hub.test",
        "--hub-workspace",
        "ws-1",
    ]
    # opencode was never configured here.
    assert by_name["opencode"].present is False
    assert by_name["opencode"].serve_args is None


def test_installed_reads_opencode_and_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(_hosts.Path, "home", classmethod(lambda cls: tmp_path))
    _hosts.HOSTS["opencode"].configure(_hosts.InstallContext(workspace=tmp_path))
    _hosts.HOSTS["codex"].configure(_hosts.InstallContext(workspace=tmp_path))

    by_name = {row.name: row for row in _hosts.installed(tmp_path)}
    # opencode stores [EXECUTABLE, *args]; the executable is dropped.
    assert by_name["opencode"].serve_args == ["agent", "mcp", "serve"]
    assert by_name["codex"].present is True
    assert by_name["codex"].serve_args == ["agent", "mcp", "serve"]


def test_status_command_reports_registered(tmp_path, monkeypatch):
    monkeypatch.setattr(_hosts.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(mcp_commands, "resolve_hub_uri", lambda *_: "http://hub.test")
    monkeypatch.delenv("SKORE_HUB_API_KEY", raising=False)
    _hosts.HOSTS["cursor"].configure(
        _hosts.InstallContext(workspace=tmp_path, hub_url="http://hub.test")
    )

    result = CliRunner().invoke(status, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "http://hub.test" in result.output
    assert "cursor" in result.output
    assert "not set" in result.output


def test_status_command_nothing_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(_hosts.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(mcp_commands, "resolve_hub_uri", lambda *_: "http://hub.test")
    monkeypatch.setenv("SKORE_HUB_API_KEY", "uid:secret")

    result = CliRunner().invoke(status, ["--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "not registered" in result.output
    assert "set" in result.output


# --------------------------------------------------------------------------- #
# serve guards
# --------------------------------------------------------------------------- #


def test_resolve_serve_workspace_api_key_returns_none():
    assert _resolve_serve_workspace(Credential("api_key"), "ws-1") is None


def test_resolve_serve_workspace_bearer_uses_flag():
    assert _resolve_serve_workspace(Credential("bearer", "t"), "ws-1") == "ws-1"


def test_resolve_serve_workspace_bearer_without_flag_errors():
    with pytest.raises(click.UsageError):
        _resolve_serve_workspace(Credential("bearer", "t"), None)


def test_serve_nonexistent_workspace_errors(tmp_path):
    missing = tmp_path / "nope"
    result = CliRunner().invoke(serve, ["--workspace", str(missing)])
    assert result.exit_code != 0
    assert "workspace does not exist" in result.output


def test_serve_no_credential_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_commands, "resolve_credential", lambda: Credential("none"))
    result = CliRunner().invoke(serve, ["--workspace", str(tmp_path)])
    assert result.exit_code != 0
    assert "no hub credential" in result.output


# --------------------------------------------------------------------------- #
# executor path confinement
# --------------------------------------------------------------------------- #


def test_executor_confines_paths_to_workspace(tmp_path):
    from skore_cli.agent.mcp import _executor

    with pytest.raises(_executor.ExecError):
        _executor._safe_path(tmp_path, "../escape.txt")
    with pytest.raises(_executor.ExecError):
        _executor._safe_path(tmp_path, "/etc/passwd")
    resolved = _executor._safe_path(tmp_path, "sub/dir/file.txt")
    assert str(resolved).startswith(str(tmp_path.resolve()))


# --------------------------------------------------------------------------- #
# MCP server build (requires the `mcp` SDK)
# --------------------------------------------------------------------------- #


def test_build_mcp_server_exposes_single_run_tool(tmp_path):
    pytest.importorskip("mcp")
    from skore_cli.agent.mcp._server import build_mcp_server

    server = build_mcp_server(_config(tmp_path))

    async def _names():
        return sorted(t.name for t in await server.list_tools())

    assert asyncio.run(_names()) == ["skore_ml_run"]
