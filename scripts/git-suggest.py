#!/usr/bin/env python3
import json
import subprocess
import os
import pyperclip

from shared.llm_client import call_llm
from config import settings

base_url = settings.LLM_BASE_URL
api_key = settings.LLM_API_KEY
model = settings.LLM_MODEL


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

Git status:
{status}

Git diff:
{diff}

Git diff --cached:
{diff_cached}
"""


def git_command(command: list[str], cwd: str):
    result = subprocess.run(
        ["git"] + command,
        text=True,
        cwd=cwd,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return result.stdout


if __name__ == "__main__":
    cwd = os.getcwd()
    prompt = COMMIT_MESSAGE_PROMPT.format(
        diff_cached=git_command(["diff", "--cached"], cwd=cwd),
        diff=git_command(["diff"], cwd=cwd),
        status=git_command(["status"], cwd=cwd),
    )
    raw = call_llm(
        base_url=base_url,
        api_key=api_key,
        model=model,
        prompt=prompt,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"LLM did not return valid JSON:\n{raw}")

    title = data["title"]
    description = data.get("description", "")
    commit_message = title

    if description:
        commit_message += f"\n\n{description}"

    print(commit_message)
    pyperclip.copy(commit_message)
