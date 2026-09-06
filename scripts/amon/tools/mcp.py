"""MCP client support: discovers tools on configured MCP servers and exposes
them as normal `tool_registry`-shaped entries.

Connection model is reconnect-per-call (one connect/`initialize`/action/close
cycle per discovery pass and per tool call), matching `registry.py`'s
existing `asyncio.run(spawn_agents(...))` sync/async bridging idiom rather
than introducing a persistent background event loop. See
MCP_SUPPORT_PLAN.md §1.2 for the tradeoff this was picked over.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

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


@asynccontextmanager
async def _connect(server_cfg: dict):
    """One connect + `initialize` cycle for either transport, yielding a
    ready `ClientSession`. Caller's `async with` block owns the close.

    `oauth` / `oauthScopes` are accepted on the config (schema stub, per
    agent-schema.md) but not read here — v1 remote auth is `headers` only.
    """
    if "command" in server_cfg:
        params = StdioServerParameters(
            command=server_cfg["command"],
            args=list(server_cfg.get("args") or []),
            env=_expand_map(server_cfg.get("env")),
        )
        transport = stdio_client(params)
    elif "url" in server_cfg:
        transport = sse_client(
            server_cfg["url"], headers=_expand_map(server_cfg.get("headers"))
        )
    else:
        raise ValueError(
            "mcp server config needs either 'command' (stdio) or 'url' (remote)"
        )

    async with transport as (read, write):
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


async def discover_mcp_tools(mcp_servers: dict[str, dict] | None) -> dict[str, dict]:
    """Connect to each non-disabled server in *mcp_servers*, list its tools,
    and return `tool_registry`-shaped entries keyed by
    ``mcp__{server_name}__{tool_name}`` (double underscore, matching the
    convention MCP hosts commonly use to avoid collisions between a
    server's tools and the harness's native ones, and between two servers
    exposing a same-named tool).

    A server that's disabled, unreachable, or times out during discovery is
    logged and skipped rather than failing the whole call — a misconfigured
    MCP server shouldn't brick an agent that doesn't strictly need it.
    """
    discovered: dict[str, dict] = {}
    for server_name, server_cfg in (mcp_servers or {}).items():
        if server_cfg.get("disabled"):
            continue
        try:
            tools = await _list_server_tools(server_cfg)
        except Exception as exc:
            logger.warning("Skipping MCP server %r: %s", server_name, exc)
            continue

        disabled_tools = set(server_cfg.get("disabledTools") or [])
        for tool in tools:
            if tool.name in disabled_tools:
                continue
            qualified_name = f"mcp__{server_name}__{tool.name}"
            discovered[qualified_name] = {
                "schema": {
                    "type": "function",
                    "function": {
                        "name": qualified_name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema
                        or {"type": "object", "properties": {}},
                    },
                },
                "fn": _make_tool_fn(server_cfg, tool.name),
                # Same default as every other tool: skip confirmation only if
                # the agent's allowed_tools names it explicitly (get_registry
                # sets this per-agent regardless of what's set here).
                "requires_confirmation": True,
            }
    return discovered
