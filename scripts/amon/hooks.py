from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID
from enum import Enum


class HookEventName(str, Enum):
    START = "start"
    STOP = "stop"
    PRE_TOOL_USE = "preToolUse"
    POST_TOOL_USE = "postToolUse"


def _run_script(
    hook: str, timeout: int = 30, **kwargs
) -> subprocess.CompletedProcess[str] | None:
    """Run a hook script, passing kwargs as environment variables.

    Example:
        run_hook("hooks/start.py", name="Leo", event="start")

    In a Python hook:
        import os
        print(os.environ["name"])  # Leo

    In a bash hook:
        echo "$name"
    """
    path = Path(hook)
    if not path.is_file():
        return None

    # Python files: run with current interpreter. Anything else (e.g. .sh): execute directly
    # (needs +x + shebang) or via bash as a fallback.
    if path.suffix == ".py":
        cmd = [sys.executable, str(path)]
    elif os.access(path, os.X_OK):
        cmd = [str(path)]
    else:
        cmd = ["bash", str(path)]

    env = os.environ.copy()
    env.update({key: str(value) for key, value in kwargs.items()})

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=timeout,
    )


def run_hook_event(
    path: str,
    session_id: UUID,
    hook_event_name: HookEventName,
    cwd: str,
    timeout: int = 30,
    **kwargs,
) -> None:

    base_env = {
        "SESSION_ID": session_id,
        "HOOK_EVENT_NAME": hook_event_name.value,
        "CWD": cwd,
    }

    if hook_event_name == "stop":
        base_env["RESPONSE"] = kwargs["response"]
    elif hook_event_name == "start":
        base_env["PROMPT"] = kwargs["prompt"]
    elif hook_event_name == "postToolUse":
        base_env["TOOL_NAME"] = kwargs["tool_name"]
        base_env["TOOL_INPUT"] = kwargs["tool_input"]
        base_env["TOOL_OUTPUT"] = kwargs["tool_output"]
    elif hook_event_name == "preToolUse":
        base_env["TOOL_NAME"] = kwargs["tool_name"]
        base_env["TOOL_INPUT"] = kwargs["tool_input"]

    resp = _run_script(path, timeout=timeout, **base_env)
    print(f"[DEBUG] content={repr(resp)}")
