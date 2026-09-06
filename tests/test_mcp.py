"""Tests for MCP client support (scripts/amon/tools/mcp.py).

Mocks the `mcp` SDK's transport/session boundary (`stdio_client`, `sse_client`,
`ClientSession`) rather than spawning a real subprocess — same call as
test_spawn_agents.py makes for its process boundary: fast and deterministic,
and the boundary being mocked is the SDK's, not our own code.

A real end-to-end stdio round trip (subprocess spawn, JSON-RPC handshake,
tools/list, tools/call) was verified manually against the installed `mcp`
SDK during the Phase 0 spike — see MCP_SUPPORT_PLAN.md.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.amon.tools import mcp as mcp_module
from scripts.amon.tools.mcp import (
    _call_mcp_tool,
    _expand_env,
    _expand_map,
    _flatten_content,
    discover_mcp_tools,
)


def _tool(name, description="", input_schema=None):
    return SimpleNamespace(
        name=name, description=description, input_schema=input_schema or {}
    )


class _FakeSession:
    """Stands in for `mcp.ClientSession`: no real transport, controllable
    tools/list and tools/call responses."""

    def __init__(self, tools=None, call_content=None, call_is_error=False, delay=0.0):
        self.tools = tools or []
        self.call_content = call_content or [SimpleNamespace(type="text", text="ok")]
        self.call_is_error = call_is_error
        self.delay = delay
        self.called_with = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def initialize(self):
        if self.delay:
            await asyncio.sleep(self.delay)

    async def list_tools(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, arguments):
        self.called_with = (name, arguments)
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(content=self.call_content, is_error=self.call_is_error)


@asynccontextmanager
async def _fake_transport(*args, **kwargs):
    yield (None, None)


@asynccontextmanager
async def _failing_transport(*args, **kwargs):
    raise OSError("no such server")
    yield  # pragma: no cover - unreachable, needed to make this an async generator


def _patch_session(session, transport_attr="stdio_client"):
    return (
        patch.object(mcp_module, transport_attr, _fake_transport),
        patch.object(mcp_module, "ClientSession", lambda read, write: session),
    )


def test_discover_mcp_tools_normal_discovery():
    session = _FakeSession(tools=[_tool("echo", "Echoes text", {"type": "object"})])
    with _patch_session(session)[0], _patch_session(session)[1]:
        discovered = asyncio.run(discover_mcp_tools({"srv": {"command": "irrelevant"}}))
    assert list(discovered.keys()) == ["mcp__srv__echo"]
    entry = discovered["mcp__srv__echo"]
    assert entry["schema"]["function"]["name"] == "mcp__srv__echo"
    assert entry["schema"]["function"]["description"] == "Echoes text"
    assert entry["schema"]["function"]["parameters"] == {"type": "object"}
    assert entry["requires_confirmation"] is True


def test_discovered_tool_fn_round_trips_through_call_tool():
    session = _FakeSession(
        tools=[_tool("echo")], call_content=[SimpleNamespace(type="text", text="HI")]
    )
    with _patch_session(session)[0], _patch_session(session)[1]:
        discovered = asyncio.run(discover_mcp_tools({"srv": {"command": "x"}}))
        # Real dispatch (agent_loop.py) calls fn(**args) synchronously, never
        # from inside a running event loop — assert outside asyncio.run too.
        result = discovered["mcp__srv__echo"]["fn"](text="hi there")
    assert result == "HI"
    assert session.called_with == ("echo", {"text": "hi there"})


def test_disabled_tools_are_filtered_out():
    session = _FakeSession(tools=[_tool("a"), _tool("b")])
    with _patch_session(session)[0], _patch_session(session)[1]:
        discovered = asyncio.run(
            discover_mcp_tools({"srv": {"command": "x", "disabledTools": ["b"]}})
        )
    assert list(discovered.keys()) == ["mcp__srv__a"]


def test_disabled_server_is_never_connected_to():
    with patch.object(mcp_module, "stdio_client") as stdio_client_mock:
        discovered = asyncio.run(
            discover_mcp_tools({"srv": {"command": "x", "disabled": True}})
        )
    assert discovered == {}
    stdio_client_mock.assert_not_called()


def test_unreachable_server_is_skipped_with_a_warning(caplog):
    with patch.object(mcp_module, "stdio_client", _failing_transport):
        with caplog.at_level("WARNING"):
            discovered = asyncio.run(
                discover_mcp_tools({"broken": {"command": "/no/such/binary"}})
            )
    assert discovered == {}
    assert any("broken" in r.getMessage() for r in caplog.records)


def test_one_broken_server_does_not_block_a_working_one():
    working = _FakeSession(tools=[_tool("ok")])

    def _client_session_factory(read, write):
        return working

    with (
        patch.object(mcp_module, "stdio_client", _failing_transport),
        patch.object(mcp_module, "sse_client", lambda *a, **kw: _fake_transport()),
        patch.object(mcp_module, "ClientSession", _client_session_factory),
    ):
        discovered = asyncio.run(
            discover_mcp_tools(
                {
                    "broken": {"command": "/no/such/binary"},
                    "good": {"url": "https://example.invalid/mcp"},
                }
            )
        )
    assert list(discovered.keys()) == ["mcp__good__ok"]


def test_discovery_timeout_is_skipped_like_any_other_failure():
    slow = _FakeSession(tools=[_tool("slow")], delay=0.2)
    with _patch_session(slow)[0], _patch_session(slow)[1]:
        discovered = asyncio.run(
            discover_mcp_tools({"srv": {"command": "x", "timeout": 0.01}})
        )
    assert discovered == {}


def test_call_tool_timeout_raises_instead_of_hanging():
    slow = _FakeSession(delay=0.2)
    with _patch_session(slow)[0], _patch_session(slow)[1]:
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(_call_mcp_tool({"command": "x", "timeout": 0.01}, "echo", {}))


def test_call_tool_uses_sse_client_for_a_url_server():
    session = _FakeSession(call_content=[SimpleNamespace(type="text", text="ok")])
    with (
        patch.object(mcp_module, "sse_client") as sse_client_mock,
        patch.object(mcp_module, "ClientSession", lambda read, write: session),
    ):
        sse_client_mock.return_value = _fake_transport()
        asyncio.run(
            _call_mcp_tool(
                {"url": "https://example.invalid/mcp", "headers": {"X": "1"}},
                "echo",
                {"a": 1},
            )
        )
    sse_client_mock.assert_called_once_with(
        "https://example.invalid/mcp", headers={"X": "1"}
    )


def test_env_var_expansion_substitutes_present_vars(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    assert _expand_env("Bearer ${MY_TOKEN}") == "Bearer secret123"


def test_env_var_expansion_leaves_missing_vars_literal(monkeypatch):
    monkeypatch.delenv("NOPE_NOT_SET", raising=False)
    assert _expand_env("${NOPE_NOT_SET}") == "${NOPE_NOT_SET}"


def test_expand_map_expands_every_value(monkeypatch):
    monkeypatch.setenv("HOST", "example.com")
    result = _expand_map({"Authorization": "Bearer ${HOST}", "Plain": "x"})
    assert result == {"Authorization": "Bearer example.com", "Plain": "x"}


def test_expand_map_passes_through_none_and_empty():
    assert _expand_map(None) is None
    assert _expand_map({}) == {}


def test_flatten_content_joins_text_blocks():
    blocks = [
        SimpleNamespace(type="text", text="hello"),
        SimpleNamespace(type="text", text="world"),
    ]
    assert _flatten_content(blocks, is_error=False) == "hello\nworld"


def test_flatten_content_summarizes_non_text_blocks():
    blocks = [SimpleNamespace(type="image", mime_type="image/png", data="abcd")]
    result = _flatten_content(blocks, is_error=False)
    assert result == "[image: image/png, 4 chars]"


def test_flatten_content_prefixes_error_results():
    blocks = [SimpleNamespace(type="text", text="tool failed")]
    assert _flatten_content(blocks, is_error=True) == "Error: tool failed"


def test_call_tool_raises_when_config_has_neither_command_nor_url():
    # _call_mcp_tool doesn't swallow errors itself — agent_loop.py's dispatch
    # loop is what turns an exception into an "Error: ..." tool result, same
    # as every other tool. discover_mcp_tools is the one that's best-effort
    # (a bad *discovery* config shouldn't brick the whole agent run).
    with pytest.raises(ValueError):
        asyncio.run(_call_mcp_tool({}, "echo", {}))


def test_discover_skips_a_malformed_server_config_instead_of_raising(caplog):
    with caplog.at_level("WARNING"):
        discovered = asyncio.run(discover_mcp_tools({"bad": {}}))
    assert discovered == {}
    assert any("bad" in r.getMessage() for r in caplog.records)
