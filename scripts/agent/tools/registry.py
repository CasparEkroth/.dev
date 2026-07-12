import asyncio
import json
from pathlib import Path

from config import AGENTS_DIR
from scripts.agent.tools.shell import run_shell, shell_readonly, READONLY_COMMANDS
from shared.file_handler import read_file, write_file
from typing import Literal

_READONLY_CMDS_STR = ", ".join(sorted(READONLY_COMMANDS))


def _load_agent_descriptions() -> dict[str, str]:
    agents_dir = AGENTS_DIR
    result = {}
    for f in sorted(agents_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            result[f.stem] = data.get("description", f.stem)
        except Exception:
            pass
    return result


_AGENT_DESCRIPTIONS = _load_agent_descriptions()
_AGENT_DESCRIPTION_STR = (
    "\n".join(f"- {name}: {desc}" for name, desc in _AGENT_DESCRIPTIONS.items())
    or "No agents configured."
)


def _spawn_agents(*args, **kwargs):
    from scripts.agent.tools.agent import spawn_agents

    return asyncio.run(spawn_agents(*args, **kwargs))


tool_registry = {
    "shell": {
        "schema": {
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Execute a shell command and return stdout.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command as list, e.g. ['python', '-m', 'unittest', 'discover']",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Optional working directory inside workspace",
                            "default": ".",
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
                "description": "Write to file",
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
                                        "description": "The old string that gets replaced by the new",
                                    },
                                    "new": {
                                        "type": "string",
                                        "description": "The new string that replaces the old string",
                                    },
                                },
                                "required": ["path", "old", "new"],
                            },
                            "description": "Items as list, e.g [{'path':'path/file.txt','old':'text that gets replaced', 'new':'text that replaces the old text'},{...}]",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
        "fn": write_file,
        "requires_confirmation": True,
    },
    "spawn_agents": {
        "schema": {
            "type": "function",
            "function": {
                "name": "spawn_agents",
                "description": "Spawn one or more agents to run tasks concurrently. Blocks until all agents finish and returns their results.",
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
                                        "enum": list(_AGENT_DESCRIPTIONS.keys()),
                                        "description": "Name of the agent to run. Available agents:\n"
                                        + _AGENT_DESCRIPTION_STR,
                                    },
                                    "task": {
                                        "type": "string",
                                        "description": "The task/instruction to give to the agent",
                                    },
                                },
                                "required": ["agent", "task"],
                            },
                            "description": "List of jobs to run in parallel",
                        },
                    },
                    "required": ["jobs"],
                },
            },
        },
        "fn": _spawn_agents,
        "requires_confirmation": True,
    },
}

TOOLS_LIST = Literal.__getitem__(
    tuple(t["schema"]["function"]["name"] for t in tool_registry.values())
)


def get_registry(
    tools: list[str] | None = None, allowed_tools: list[str] | None = None
) -> dict:
    if tools is None:
        return {}

    register = {k: v for k, v in tool_registry.items() if k in tools}

    if allowed_tools is None:
        return register

    for k, v in register.items():
        if k in allowed_tools:
            v["requires_confirmation"] = False

    return register
