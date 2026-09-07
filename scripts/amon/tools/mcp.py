"""MCP client support: discovers tools on configured MCP servers and exposes
them as normal `tool_registry`-shaped entries.

Default connection model is reconnect-per-call (one connect/`initialize`/
action/close cycle per discovery pass and per tool call), matching
`registry.py`'s existing `asyncio.run(spawn_agents(...))` sync/async bridging
idiom. Servers that hold in-process session state across calls (e.g. browser
automation like `@playwright/mcp`) can opt in with `"persistent": true`, which
keeps one `ClientSession` alive on a dedicated background event-loop thread
for the caller-defined lifetime (one headless run, or one interactive
agent-session until `/agent` switch / exit). See MCP_SUPPORT_PLAN.md §1.2.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

from config import DEFAULT_MCP_TIMEOUT

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: str) -> str:
    """Replace ``${VAR_NAME}`` with the host process's env var of that name.

    A reference to an unset var is left literal (not swapped for ``""``) so
    a misconfiguration fails loudly downstream (e.g. a literal
    ``${MY_TOKEN}`` string in an Authorization header) instead of silently
    connecting unauthenticated.
    """
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def _expand_map(mapping: dict[str, str] | None) -> dict[str, str] | None:
    if not mapping:
        return mapping
    return {k: _expand_env(v) for k, v in mapping.items()}


def _build_transport(server_cfg: dict):
    """Return the transport context manager for *server_cfg* (stdio or SSE).

    Shared by the reconnect-per-call path (`_connect`) and the persistent
    path (`_PersistentMcpConnection`) so command/args/env/url/headers
    handling cannot drift between them.

    `oauth` / `oauthScopes` are accepted on the config (schema stub, per
    agent-schema.md) but not read here — v1 remote auth is `headers` only.
    """
    if "command" in server_cfg:
        params = StdioServerParameters(
            command=server_cfg["command"],
            args=list(server_cfg.get("args") or []),
            env=_expand_map(server_cfg.get("env")),
        )
        return stdio_client(params)
    if "url" in server_cfg:
        return sse_client(
            server_cfg["url"], headers=_expand_map(server_cfg.get("headers"))
        )
    raise ValueError(
        "mcp server config needs either 'command' (stdio) or 'url' (remote)"
    )


@asynccontextmanager
async def _connect(server_cfg: dict):
    """One connect + `initialize` cycle for either transport, yielding a
    ready `ClientSession`. Caller's `async with` block owns the close.
    """
    async with _build_transport(server_cfg) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _flatten_content(blocks: list[Any], *, is_error: bool) -> str:
    """MCP `tools/call` results are a list of content blocks, not a bare
    string. Text blocks are concatenated; non-text blocks (image/audio/
    resource) are summarized rather than inlined raw — `truncate_tool_output`
    upstream already handles an oversized *string*, so this only needs to
    get the content down to a string, not to a size-bounded one.
    """
    parts = []
    for block in blocks or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
        else:
            kind = getattr(block, "type", type(block).__name__)
            mime = getattr(block, "mime_type", "unknown")
            size = len(getattr(block, "data", "") or "")
            parts.append(f"[{kind}: {mime}, {size} chars]")
    text = "\n".join(parts)
    return f"Error: {text}" if is_error else text


async def _list_server_tools(server_cfg: dict) -> list[Any]:
    async def _run() -> list[Any]:
        async with _connect(server_cfg) as session:
            result = await session.list_tools()
            return result.tools

    return await asyncio.wait_for(
        _run(), server_cfg.get("timeout") or DEFAULT_MCP_TIMEOUT
    )


async def _call_mcp_tool(server_cfg: dict, tool_name: str, arguments: dict) -> str:
    async def _run() -> str:
        async with _connect(server_cfg) as session:
            result = await session.call_tool(tool_name, arguments)
            return _flatten_content(result.content, is_error=result.is_error)

    return await asyncio.wait_for(
        _run(), server_cfg.get("timeout") or DEFAULT_MCP_TIMEOUT
    )


def _make_tool_fn(server_cfg: dict, tool_name: str):
    """Sync bridging wrapper for one discovered tool — a fresh factory call
    per tool so each closure binds its own `tool_name` (not a loop variable
    shared and mutated across iterations).
    """

    def _fn(**kwargs) -> str:
        return asyncio.run(_call_mcp_tool(server_cfg, tool_name, kwargs))

    return _fn


class _PersistentMcpConnection:
    """Keeps one MCP ClientSession alive across multiple tool calls by
    running it on a dedicated background event loop thread, bridged to
    the synchronous tool-dispatch call stack via
    ``run_coroutine_threadsafe``. Reconnect-per-call (``_call_mcp_tool``) is
    NOT reused here — this owns the connection for its whole lifetime
    instead of one connect/close per call.
    """

    def __init__(self, server_cfg: dict):
        self._server_cfg = server_cfg
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="amon-mcp-persistent"
        )
        self._thread.start()
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    def _timeout(self) -> float:
        return float(self._server_cfg.get("timeout") or DEFAULT_MCP_TIMEOUT)

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(
            self._timeout()
        )

    def connect(self) -> None:
        async def _open():
            self._exit_stack = AsyncExitStack()
            transport = _build_transport(self._server_cfg)
            read, write = await self._exit_stack.enter_async_context(transport)
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self._session.initialize()

        self._run(_open())

    def list_tools(self) -> list[Any]:
        if self._session is None:
            raise RuntimeError("Persistent MCP connection is not open")
        return self._run(self._session.list_tools()).tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        if self._session is None:
            raise RuntimeError("Persistent MCP connection is not open")
        result = self._run(self._session.call_tool(tool_name, arguments))
        return _flatten_content(result.content, is_error=result.is_error)

    def close(self) -> None:
        async def _close():
            if self._exit_stack is not None:
                await self._exit_stack.aclose()
                self._exit_stack = None
                self._session = None

        try:
            if self._loop.is_running():
                try:
                    self._run(_close())
                except Exception:
                    # anyio transports (stdio_client) tie cancel scopes to
                    # the asyncio Task that opened them; run_coroutine_threadsafe
                    # gives close() a different Task than connect() used, so
                    # the underlying transport's __aexit__ reliably raises here
                    # even though the subprocess still exits. Non-fatal: don't
                    # let teardown mask a successful run_task() result.
                    logger.warning(
                        "Error closing persistent MCP connection", exc_info=True
                    )
        finally:
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)


def _make_persistent_tool_fn(conn: _PersistentMcpConnection, tool_name: str):
    """Sync callable for a tool on a live persistent connection — no
    ``asyncio.run``; the connection object already bridges into its loop."""

    def _fn(**kwargs) -> str:
        return conn.call_tool(tool_name, kwargs)

    return _fn


def _registry_entry(qualified_name: str, tool: Any, fn) -> dict:
    return {
        "schema": {
            "type": "function",
            "function": {
                "name": qualified_name,
                "description": tool.description or "",
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        },
        "fn": fn,
        # Same default as every other tool: skip confirmation only if
        # the agent's allowed_tools names it explicitly (get_registry
        # sets this per-agent regardless of what's set here).
        "requires_confirmation": True,
    }


async def discover_mcp_tools(
    mcp_servers: dict[str, dict] | None,
) -> tuple[dict[str, dict], list[Callable[[], None]]]:
    """Connect to each non-disabled server in *mcp_servers*, list its tools,
    and return ``(entries, closers)`` where *entries* are `tool_registry`-
    shaped dicts keyed by ``mcp__{server_name}__{tool_name}`` and *closers*
    is a list of zero-arg sync callables that tear down any persistent
    connections opened during this call (empty when no server used
    ``persistent: true``).

    A server that's disabled, unreachable, or times out during discovery is
    logged and skipped rather than failing the whole call — a misconfigured
    MCP server shouldn't brick an agent that doesn't strictly need it. The
    same best-effort policy applies to ``persistent: true`` servers.
    """
    discovered: dict[str, dict] = {}
    closers: list[Callable[[], None]] = []

    for server_name, server_cfg in (mcp_servers or {}).items():
        if server_cfg.get("disabled"):
            continue

        if server_cfg.get("persistent"):
            conn = _PersistentMcpConnection(server_cfg)
            try:
                await asyncio.to_thread(conn.connect)
                tools = await asyncio.to_thread(conn.list_tools)
            except Exception as exc:
                logger.warning("Skipping MCP server %r: %s", server_name, exc)
                try:
                    conn.close()
                except Exception:
                    pass
                continue
            closers.append(conn.close)
            make_fn = lambda t, c=conn: _make_persistent_tool_fn(c, t)  # noqa: E731
        else:
            try:
                tools = await _list_server_tools(server_cfg)
            except Exception as exc:
                logger.warning("Skipping MCP server %r: %s", server_name, exc)
                continue
            make_fn = lambda t, cfg=server_cfg: _make_tool_fn(cfg, t)  # noqa: E731

        disabled_tools = set(server_cfg.get("disabledTools") or [])
        for tool in tools:
            if tool.name in disabled_tools:
                continue
            qualified_name = f"mcp__{server_name}__{tool.name}"
            discovered[qualified_name] = _registry_entry(
                qualified_name, tool, make_fn(tool.name)
            )

    return discovered, closers
