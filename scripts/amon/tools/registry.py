"""Tool registry: built-in schemas + per-agent binding (guards, cwd, confirmation)."""

from __future__ import annotations

from functools import partial
from typing import Literal

from scripts.amon.memory import load_session_cwd, save_session_cwd
from scripts.amon.tools.agent import load_ready_agents
from scripts.amon.tools.tool_schemas import (
    _spawn_agents as _spawn_agents,  # re-export for tests
    build_base_tool_registry,
    build_spawn_agents_entry,
)

# Tools that accept server-side path/command guards (not model-visible params).
_PATH_GUARDED_TOOLS = frozenset(
    {"read_file", "write_file", "shell", "shell_readonly", "set_cwd"}
)
_COMMAND_GUARDED_TOOLS = frozenset({"shell", "shell_readonly"})
#: Tools that get the current session id bound server-side (not a model-visible param).
_SESSION_BOUND_TOOLS = frozenset({"todo_write"})
#: Tools whose 'cwd' argument defaults to the session's sticky set_cwd value
#: (set on the same registry build, or loaded from `.meta.json` on resume)
#: when the model omits it, instead of the tool's own hardcoded ".".
_CWD_STICKY_TOOLS = frozenset({"shell", "shell_readonly"})


def _bind_sticky_cwd(fn, cwd_state: dict):
    """Default *fn*'s 'cwd' kwarg to `cwd_state["cwd"]` when the caller omits it."""

    def wrapped(**kwargs):
        if kwargs.get("cwd") is None and cwd_state.get("cwd"):
            kwargs["cwd"] = cwd_state["cwd"]
        return fn(**kwargs)

    return wrapped


def _bind_set_cwd(fn, cwd_state: dict, session_id: object | None):
    """Make a successful `set_cwd` call update *cwd_state* (immediate effect
    for the rest of this run) and persist to `.meta.json` (effect on resume).

    *fn* raises on an invalid/denied directory, so no update happens unless
    the underlying call actually succeeded.
    """

    def wrapped(cwd: str, **kwargs) -> str:
        message = fn(cwd=cwd, **kwargs)
        cwd_state["cwd"] = cwd
        if session_id:
            save_session_cwd(session_id, cwd)
        return message

    return wrapped


tool_registry = build_base_tool_registry()

# Load agents after tool_registry exists so the wildcard validator can import it.
READY_AGENTS = load_ready_agents()
_AGENT_DESCRIPTION_STR = (
    "\n".join(f"- {name}: {agent.description}" for name, agent in READY_AGENTS.items())
    or "No agents configured."
)

tool_registry["spawn_agents"] = build_spawn_agents_entry(
    list(READY_AGENTS.keys()),
    _AGENT_DESCRIPTION_STR,
)

TOOLS_LIST = Literal.__getitem__(
    tuple(t["schema"]["function"]["name"] for t in tool_registry.values())
)


def get_registry(
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    allow_paths: list[str] | None = None,
    deny_paths: list[str] | None = None,
    denied_commands: list[str] | None = None,
    session_id: object | None = None,
    extra_tools: dict | None = None,
) -> dict:
    """Select this agent's tools, with its own confirmation and path policy.

    Each entry is a copy: writing the flag back onto the shared ``tool_registry``
    made it process-wide, so one permissive agent disabled confirmation for all.

    ``allow_paths`` / ``deny_paths`` / ``denied_commands`` / ``session_id`` are
    bound onto the tool callables with ``functools.partial`` — they are never
    added to the JSON schema the model sees.

    ``extra_tools``: per-run, already-built entries (e.g. from
    ``discover_mcp_tools``) merged in ahead of everything below — a wildcard
    agent (``"tools": ["*"]``) picks these up for free, and every guard/
    confirmation/truncation rule below applies to them exactly like a native
    tool, since they're structurally identical entries.

    ``["*"]`` in ``tools`` / ``allowed_tools`` expands to every registered
    tool name, resolved here rather than at agent-load time — this is the
    only point guaranteed to run after ``tool_registry`` is fully built
    (``spawn_agents`` is added to it after ``READY_AGENTS`` loads, since its
    schema needs the agent list; expanding any earlier would silently drop it
    from every wildcard agent).
    """
    if tools is None:
        return {}

    registry = {**tool_registry, **(extra_tools or {})}

    if tools == ["*"]:
        tools = list(registry.keys())

    allowed = allowed_tools or []
    if allowed == ["*"]:
        allowed = list(registry.keys())
    allow_paths = list(allow_paths or [])
    deny_paths = list(deny_paths or [])
    denied_commands = list(denied_commands or [])
    guard = allow_paths or deny_paths or denied_commands

    # Shared across every tool built by this call, so a set_cwd call takes
    # immediate effect on shell/shell_readonly calls later in the same run,
    # not just after the session's .meta.json is re-read on the next prompt.
    cwd_state = {"cwd": load_session_cwd(session_id) if session_id else None}

    out: dict = {}
    for k, v in registry.items():
        if k not in tools:
            continue
        entry = {**v, "requires_confirmation": k not in allowed}
        if guard and k in _PATH_GUARDED_TOOLS:
            kwargs: dict = {}
            if allow_paths or deny_paths:
                kwargs["allow_paths"] = allow_paths
                kwargs["deny_paths"] = deny_paths
            if denied_commands and k in _COMMAND_GUARDED_TOOLS:
                kwargs["denied_commands"] = denied_commands
            if kwargs:
                entry["fn"] = partial(v["fn"], **kwargs)
        if k in _SESSION_BOUND_TOOLS:
            entry["fn"] = partial(
                entry["fn"], session_id=str(session_id) if session_id else None
            )
        if k in _CWD_STICKY_TOOLS:
            entry["fn"] = _bind_sticky_cwd(entry["fn"], cwd_state)
        if k == "set_cwd":
            entry["fn"] = _bind_set_cwd(entry["fn"], cwd_state, session_id)
        out[k] = entry
    return out
