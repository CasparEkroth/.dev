#!/usr/bin/env python3
"""Pre-flight check: every tool an agent's system_prompt tells it to call by
name must be in that agent's allowed_tools, not just tools -- otherwise the
call is silently unusable in headless mode (no confirmation UI exists to
grant it). Run before spec-script ever invokes amon. Exit 0 if every
pipeline agent passes, exit 1 with a report otherwise.

See scripts/build-from-spec/SPEC-PIPELINE-WORKFLOW-ANALYSIS.md §2.2/§2.6/§3.1
for the incident this guards against.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

AGENTS_DIR = Path("~/.amon/agents").expanduser()

PIPELINE_AGENTS = [
    "spec-orchestrator",
    "spec-intake",
    "architect",
    "spec-dev",
    "spec-test-runner",
    "spec-reviewer",
    "docs-writer",
]

KNOWN_TOOLS = {
    "shell", "shell_readonly", "read_file", "write_file",
    "load_skill", "todo_write", "set_cwd", "spawn_agents",
}


def mentioned_tools(system_prompt: str) -> set[str]:
    backticked = set(re.findall(r"`([a-z_]+)`", system_prompt))
    return backticked & KNOWN_TOOLS


def check_agent(name: str) -> list[str]:
    path = AGENTS_DIR / f"{name}.json"
    if not path.is_file():
        return [f"{name}: agent file not found at {path}"]

    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{name}: invalid JSON ({exc})"]

    tools = set(config.get("tools", []))
    allowed = set(config.get("allowed_tools", []))
    if "*" in tools:
        tools = KNOWN_TOOLS | tools

    problems = []
    for tool in sorted(mentioned_tools(config.get("system_prompt", ""))):
        if tool not in tools:
            problems.append(
                f"{name}: system_prompt mentions `{tool}` but it isn't in tools at all"
            )
        elif tool not in allowed:
            problems.append(
                f"{name}: `{tool}` is in tools but missing from allowed_tools "
                "-- silently unusable in headless mode"
            )
    return problems


def main() -> int:
    all_problems = []
    for name in PIPELINE_AGENTS:
        all_problems.extend(check_agent(name))

    if all_problems:
        print("preflight-check: pipeline agent config problems found:", file=sys.stderr)
        for p in all_problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"preflight-check: {len(PIPELINE_AGENTS)} pipeline agents OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
