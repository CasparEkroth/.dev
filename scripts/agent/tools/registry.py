from scripts.agent.tools.shell import run_shell, shell_readonly, READONLY_COMMANDS
from shared.file_handler import read_file, write_file
from typing import Literal

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
                "description": f"Execute a readonly shell command like: {READONLY_COMMANDS} and return stdout.",
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
    # "spawn_agent": {},
}

TOOLS_LIST = Literal[[t["schema"]["function"]["name"] for t in tool_registry.values()]]


def get_registry(
    tools: list[TOOLS_LIST] = None, allowd_tools: list[TOOLS_LIST] = None
) -> dict:
    if tools is None:
        return {}

    register = {k: v for k, v in tool_registry.items() if k in tools}

    if allowd_tools is None:
        return register

    for k, v in register.items():
        if k in allowd_tools:
            v["requires_confirmation"] = False

    return register
