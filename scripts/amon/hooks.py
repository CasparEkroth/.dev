from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 10_000


class HookEventName(str, Enum):
    AGENT_SPAWN = "agentSpawn"
    START = "start"
    STOP = "stop"
    PRE_TOOL_USE = "preToolUse"
    POST_TOOL_USE = "postToolUse"


#: Exit code with which a preToolUse hook blocks the tool it matched.
BLOCK_EXIT_CODE = 2


def _run_script(
    hook: str, payload: dict, env_extra: dict, timeout_ms: int
) -> subprocess.CompletedProcess[str] | None:
    """Run one hook script with *payload* on stdin and *env_extra* in its env.

    Returns None when the script does not exist or could not be run; a hook is
    an observer and must never break the run that triggered it.
    """
    path = Path(hook).expanduser().resolve()
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
    env.update({key: str(value) for key, value in env_extra.items()})

    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            input=json.dumps(payload),
            timeout=timeout_ms / 1000,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("hook %s failed to run: %s", path, exc)
        return None


def run_hook_event(
    specs: list[dict],
    session_id: UUID,
    hook_event_name: HookEventName,
    cwd: str,
    **kwargs,
) -> tuple[str, str | None]:
    """Run the hooks configured for one event.

    Returns their combined stdout (successful hooks only, for the events whose
    output joins the conversation) and the reason a preToolUse hook blocked the
    tool, if one did.
    """
    payload = {
        "hook_event_name": hook_event_name.value,
        "cwd": cwd,
        "session_id": str(session_id),
        **kwargs,
    }
    # Legacy env-var names, kept for hooks written before the stdin payload.
    env_extra = {
        "SESSION_ID": session_id,
        "HOOK_EVENT_NAME": hook_event_name.value,
        "CWD": cwd,
        **{key.upper(): value for key, value in kwargs.items()},
    }

    out: list[str] = []
    blocked: str | None = None
    for spec in specs:
        matcher = spec.get("matcher")
        if matcher and not fnmatch(str(kwargs.get("tool_name", "")), matcher):
            continue

        done = _run_script(
            spec["command"],
            payload,
            env_extra,
            spec.get("timeout_ms") or DEFAULT_TIMEOUT_MS,
        )
        if done is None:
            continue
        if done.returncode == 0:
            out.append(done.stdout or "")
            continue
        if (
            done.returncode == BLOCK_EXIT_CODE
            and hook_event_name == HookEventName.PRE_TOOL_USE
        ):
            blocked = blocked or (done.stderr or "blocked by hook").strip()
            continue
        logger.warning(
            "hook %s exited %s: %s", spec["command"], done.returncode, done.stderr
        )

    return "".join(out), blocked
