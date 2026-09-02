#!/usr/bin/env python3
"""Example postToolUse hook: gate every write_file call through python-validate.

Wire this into an agent's `hooks.postToolUse` with `"matcher": "write_file"`
(see ../agent-with-test-gate.json). It runs the python-validate skill's
check.py (syntax -> ruff -> mypy; pytest is skipped by default since this
fires on every write_file call, and a full test run per write is too slow)
against every .py file the call touched. Any failure is printed to stdout,
which the harness appends to the conversation as its own message right after
the turn's tool replies -- so the model finds out its edit doesn't pass
before claiming the change works. A clean check prints nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_CHECK_PY = "~/.amon/skills/python-validate/scripts/check.py"


def _touched_py_files(tool_input: dict) -> list[str]:
    content = tool_input.get("content") or []
    paths = {item.get("path") for item in content if isinstance(item, dict)}
    return sorted(p for p in paths if p and p.endswith(".py"))


def _first_issue(summary: dict) -> str | None:
    syntax_issues = summary.get("syntax_issues") or []
    if syntax_issues:
        issue = syntax_issues[0]
        return f"syntax error: {issue.get('message')} (line {issue.get('line')})"
    for stage in ("ruff", "mypy"):
        issues = (summary.get(stage) or {}).get("issues") or []
        if issues:
            issue = issues[0]
            code = f" {issue['code']}" if issue.get("code") else ""
            return f"{stage}{code}: {issue.get('message')} (line {issue.get('line')})"
    return None


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    if payload.get("tool_name") != "write_file":
        return

    files = _touched_py_files(payload.get("tool_input") or {})
    if not files:
        return

    check_py = Path(
        os.environ.get("PYTHON_VALIDATE_CHECK", DEFAULT_CHECK_PY)
    ).expanduser()
    if not check_py.is_file():
        return  # skill isn't installed for this agent -- nothing to gate with

    messages = []
    for path in files:
        if not Path(path).is_file():
            continue  # e.g. removed since the write
        result = subprocess.run(
            [sys.executable, str(check_py), path, "--no-tests"],
            capture_output=True,
            text=True,
        )
        try:
            summary = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        if not summary.get("overall_ok", True):
            messages.append(f"{path}: {_first_issue(summary) or 'failed validation'}")

    if messages:
        print("python-validate found issues:\n" + "\n".join(messages))


if __name__ == "__main__":
    main()
