import asyncio
import json
from typing import Literal

from config import DEFAULT_SHELL_TIMEOUT
from scripts.amon.tools.agent import load_ready_agents
from scripts.amon.tools.shell import run_shell, shell_readonly, READONLY_COMMANDS
from shared.file_handler import read_file, write_file
from scripts.amon.tools.skills import load_skill

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
                    "Write to file. An entry whose 'path' does not exist yet is "
                    "CREATED (with any missing parent directories) when 'old' is "
                    "empty and 'new' holds the content. For an existing file an "
                    "empty 'old' appends, otherwise the first occurrence of 'old' "
                    "is replaced by 'new'."
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
                "Spawn one or more agents to run tasks concurrently. Blocks until all "
                "agents finish. Returns a JSON string: a list of result objects with keys "
                "ok, agent, task, result, error, usage, turns, tools_used, session_id. "
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
