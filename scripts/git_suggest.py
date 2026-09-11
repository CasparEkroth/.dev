#!/usr/bin/env python3
"""Suggest a commit message from the staged git diff via the configured LLM."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pyperclip

from shared.llm_client import call_llm

# Keep prompt well under typical model limits (500k tokens here would be ~2M
# chars; 120k chars of diff is ~30-40k tokens and enough for a good message).
MAX_DIFF_CHARS = 120_000
MAX_STATUS_CHARS = 20_000

COMMIT_MESSAGE_PROMPT = """
Generate a Git commit message from the given status and diff.

Return only valid JSON with this exact shape:

{{
  "title": "Short title under 50 characters",
  "description": "Longer description wrapped naturally. Explain what changed and why, not every tiny detail."
}}

Rules:
- Use imperative mood
- No markdown
- Be specific
- title must be under 50 characters
- description must be 1-3 sentences
- description may be an empty string if no description is needed
- Return only valid JSON
- Do not include explanations
- If the diff is truncated, base the message on what is present and the summary

Git status:
{status}

Diff summary (git diff --cached --stat):
{diff_stat}

Git diff --cached:
{diff_cached}
"""


def git_command(command: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git"] + command,
        text=True,
        cwd=cwd,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return result.stdout


def truncate_text(text: str, limit: int, label: str) -> str:
    """Cap *text* at *limit* chars, keeping a head and tail sample."""
    if len(text) <= limit:
        return text

    # Leave room for the marker so the returned string stays near *limit*.
    marker_budget = 120
    usable = max(limit - marker_budget, 0)
    head_len = usable * 7 // 10
    tail_len = usable - head_len
    omitted = len(text) - head_len - tail_len
    marker = f"\n\n... [{omitted:,} chars of {label} truncated] ...\n\n"
    return f"{text[:head_len]}{marker}{text[-tail_len:] if tail_len else ''}"


def build_prompt(cwd: str) -> str:
    """Collect staged changes and build a size-capped LLM prompt."""
    status = git_command(["status"], cwd=cwd)
    diff_stat = git_command(["diff", "--cached", "--stat"], cwd=cwd)
    diff_cached = git_command(["diff", "--cached"], cwd=cwd)

    if not diff_cached.strip():
        raise RuntimeError(
            "No staged changes. Stage files with `git add` before running git-suggest."
        )

    original_diff_len = len(diff_cached)
    status = truncate_text(status, MAX_STATUS_CHARS, "status")
    diff_cached = truncate_text(diff_cached, MAX_DIFF_CHARS, "diff")

    if original_diff_len > MAX_DIFF_CHARS:
        print(
            f"warning: staged diff is {original_diff_len:,} chars; "
            f"sending first/last ~{MAX_DIFF_CHARS:,} chars plus --stat summary",
            file=sys.stderr,
        )

    return COMMIT_MESSAGE_PROMPT.format(
        status=status,
        diff_stat=diff_stat or "(empty)",
        diff_cached=diff_cached,
    )


def suggest_commit_message(cwd: str | None = None) -> str:
    """Return a suggested commit message for staged changes in *cwd*."""
    cwd = cwd or os.getcwd()
    prompt = build_prompt(cwd)
    raw = call_llm(prompt=prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"LLM did not return valid JSON:\n{raw}") from None

    title = data["title"]
    description = data.get("description", "") or ""
    if description:
        return f"{title}\n\n{description}"
    return title


if __name__ == "__main__":
    commit_message = suggest_commit_message()
    print(commit_message)
    pyperclip.copy(commit_message)
