from scripts.agent.tools.shell import run_shell


tool_registry = {
    # "read_spreadsheet": {
    #     "schema": {
    #         "type": "function",
    #         "function": {
    #             "name": "read_spreadsheet",
    #             "description": "Read cell values from a spreadsheet.",
    #             "parameters": {
    #                 "type": "object",
    #                 "properties": {
    #                     "path": {"type": "string"},
    #                     "sheet": {"type": "string"},
    #                 },
    #                 "required": ["path"],
    #             },
    #         },
    #     },
    #     "fn": read_spreadsheet_impl,
    #     "requires_confirmation": False,
    # },
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
}