import asyncio
import json
from functools import partial
from typing import Literal

from config import DEFAULT_MAX_PARALLEL, DEFAULT_SHELL_TIMEOUT
from scripts.amon.tools.agent import load_ready_agents
from scripts.amon.tools.shell import run_shell, shell_readonly, READONLY_COMMANDS
from shared.file_handler import read_file, write_file
from scripts.amon.tools.skills import load_skill
from scripts.amon.tools.todo import write_todos

# Tools that accept server-side path/command guards (not model-visible params).
_PATH_GUARDED_TOOLS = frozenset({"read_file", "write_file", "shell", "shell_readonly"})
_COMMAND_GUARDED_TOOLS = frozenset({"shell", "shell_readonly"})
#: Tools that get the current session id bound server-side (not a model-visible param).
_SESSION_BOUND_TOOLS = frozenset({"todo_write"})

_READONLY_CMDS_STR = ", ".join(sorted(READONLY_COMMANDS))


def _spawn_agents(*args, **kwargs):
    from scripts.amon.tools.agent import spawn_agents

    results = asyncio.run(spawn_agents(*args, **kwargs))
    # Tool calls need a string/JSON-serializable payload for the LLM.
    return json.dumps(results, ensure_ascii=False, indent=2)


# tool_registry must be defined before load_ready_agents() is called,
# because Agent.expand_wildcards lazily imports tool_registry from this module.
tool_registry = {
    "shell": {
        "schema": {
            "type": "function",
            "function": {
                "name": "shell",
                "description": (
                    "Execute a shell command and return stdout. Pass a string to "
                    "use shell features (pipes, redirects, &&), or a list to exec "
                    "argv directly. Raise 'timeout' for long jobs; on expiry the "
                    "output captured so far is returned."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "string"},
                            ],
                            "description": "Command as list, e.g. ['python', '-m', 'unittest', 'discover'], or as a shell string, e.g. 'pytest tests/ | tail -5'",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Optional working directory inside workspace",
                            "default": ".",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": f"Seconds to wait before giving up (default {DEFAULT_SHELL_TIMEOUT}). Increase it for solvers, builds and test suites.",
                            "default": DEFAULT_SHELL_TIMEOUT,
                        },
                        "shell": {
                            "type": "boolean",
                            "description": "Run through the shell (implied by a string command). A shell string has no argv boundary, so only use it when shell features are needed.",
                            "default": False,
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        "fn": run_shell,
        "requires_confirmation": True,
    },
    "shell_readonly": {
        "schema": {
            "type": "function",
            "function": {
                "name": "shell_readonly",
                "description": "Execute a readonly shell command like: "
                + _READONLY_CMDS_STR
                + " and return stdout.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command as list, e.g. ['grep', '-n', 'import asyncio']",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Optional working directory inside workspace",
                            "default": ".",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": f"Seconds to wait before giving up (default {DEFAULT_SHELL_TIMEOUT}).",
                            "default": DEFAULT_SHELL_TIMEOUT,
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        "fn": shell_readonly,
        "requires_confirmation": True,
    },
    "read_file": {
        "schema": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a section off a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {
                            "type": "integer",
                            "description": "Optional 1-based starting line, inclusive",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Optional 1-based ending line, inclusive",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        "fn": read_file,
        "requires_confirmation": True,
    },
    "write_file": {
        "schema": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": (
                    "Write to file. An empty 'old' appends, or creates the file "
                    "(with parent directories) when 'path' does not exist; "
                    "otherwise the first occurrence of 'old' becomes 'new'. Set "
                    "'overwrite': true to replace the file's ENTIRE contents with "
                    "'new' in one call (creating it and any parent directories if "
                    "needed) — 'old' is ignored. Use overwrite for a new "
                    "implementation, a full rewrite of a function/file, or any "
                    "change too large to express as a handful of old/new patches; "
                    "use old/new for small, surgical edits."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "old": {
                                        "type": "string",
                                        "description": "The old string that gets replaced by the new. Ignored when 'overwrite' is true.",
                                    },
                                    "new": {
                                        "type": "string",
                                        "description": "The new string that replaces the old string, or the file's full new content when 'overwrite' is true.",
                                    },
                                    "overwrite": {
                                        "type": "boolean",
                                        "description": "Replace the whole file with 'new' instead of patching. Default false.",
                                        "default": False,
                                    },
                                },
                                "required": ["path", "old", "new"],
                            },
                            "description": "Items as list, e.g [{'path':'path/file.txt','old':'text that gets replaced', 'new':'text that replaces the old text'},{'path':'path/new_module.py','old':'','new':'<full file content>','overwrite':true}]",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
        "fn": write_file,
        "requires_confirmation": True,
    },
    "load_skill": {
        "schema": {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": "Load a skill by path and return its content plus discovered resources.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_path": {
                            "type": "string",
                            "description": "Path to the skill directory (e.g. '.amon/skills/python-validation')",
                        },
                    },
                    "required": ["skill_path"],
                },
            },
        },
        "fn": load_skill,
        "requires_confirmation": True,
    },
    "todo_write": {
        "schema": {
            "type": "function",
            "function": {
                "name": "todo_write",
                "description": (
                    "Set/replace the checklist of steps for the current task. Call "
                    "this first for any request with more than one distinct step, "
                    "before any other tool call. Replaces the ENTIRE list each "
                    "call — resend items you're keeping, don't just send the diff. "
                    "Keep at most one item 'in_progress' at a time, and mark an "
                    "item 'completed' immediately after finishing it rather than "
                    "batching updates at the end."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "One concrete step, e.g. 'Add overwrite mode to write_file'",
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "completed"],
                                    },
                                },
                                "required": ["content", "status"],
                            },
                            "description": "The full checklist, e.g. [{'content': 'Read the affected files', 'status': 'completed'}, {'content': 'Implement the change', 'status': 'in_progress'}, {'content': 'Add tests', 'status': 'pending'}]",
                        },
                    },
                    "required": ["todos"],
                },
            },
        },
        "fn": write_todos,
        "requires_confirmation": True,
    },
}

# Load agents after tool_registry exists so the wildcard validator can import it.
READY_AGENTS = load_ready_agents()
_AGENT_DESCRIPTION_STR = (
    "\n".join(f"- {name}: {agent.description}" for name, agent in READY_AGENTS.items())
    or "No agents configured."
)

tool_registry["spawn_agents"] = {
    "schema": {
        "type": "function",
        "function": {
            "name": "spawn_agents",
            "description": (
                "Spawn one or more agents to run tasks concurrently as child "
                "processes. Blocks until all agents finish. Returns a JSON string: "
                "a list of result objects with keys ok, agent, task, result, error, "
                "usage, turns, tools_used, session_id. "
                "Check ok on each item — result may be partial when ok is false "
                "(e.g. max turns). Sessions are not saved unless save_session=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "jobs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent": {
                                    "type": "string",
                                    "enum": list(READY_AGENTS.keys()),
                                    "description": "Name of the agent to run. Available agents:\n"
                                    + _AGENT_DESCRIPTION_STR,
                                },
                                "task": {
                                    "type": "string",
                                    "description": "The task/instruction to give to the agent",
                                },
                                "save_session": {
                                    "type": "boolean",
                                    "description": (
                                        "If true, persist this job's session. "
                                        "Default false."
                                    ),
                                    "default": False,
                                },
                                "session_id": {
                                    "type": "string",
                                    "description": (
                                        "External session id for this child. "
                                        "Correlates logs and makes a crashed "
                                        "run resumable."
                                    ),
                                },
                                "model": {
                                    "type": "string",
                                    "description": "Override the agent model for this job only.",
                                },
                                "max_turns": {
                                    "type": "integer",
                                    "description": "Override max turns for this job only.",
                                },
                            },
                            "required": ["agent", "task"],
                        },
                        "description": "List of jobs to run in parallel",
                    },
                    "max_parallel": {
                        "type": "integer",
                        "description": f"Concurrent child processes (default {DEFAULT_MAX_PARALLEL}).",
                        "default": DEFAULT_MAX_PARALLEL,
                    },
                    "timeout_s": {
                        "type": "number",
                        "description": "Per-job wall-clock limit; the child is killed on expiry. Omit for no limit.",
                    },
                    "output": {
                        "type": "string",
                        "description": (
                            "Optional path to write the full result list as JSON, "
                            "even when some jobs failed. Use as a checkpoint."
                        ),
                    },
                },
                "required": ["jobs"],
            },
        },
    },
    "fn": _spawn_agents,
    "requires_confirmation": True,
}

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
) -> dict:
    """Select this agent's tools, with its own confirmation and path policy.

    Each entry is a copy: writing the flag back onto the shared ``tool_registry``
    made it process-wide, so one permissive agent disabled confirmation for all.

    ``allow_paths`` / ``deny_paths`` / ``denied_commands`` / ``session_id`` are
    bound onto the tool callables with ``functools.partial`` — they are never
    added to the JSON schema the model sees.
    """
    if tools is None:
        return {}

    allowed = allowed_tools or []
    allow_paths = list(allow_paths or [])
    deny_paths = list(deny_paths or [])
    denied_commands = list(denied_commands or [])
    guard = allow_paths or deny_paths or denied_commands

    out: dict = {}
    for k, v in tool_registry.items():
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
        out[k] = entry
    return out
