import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import json
import subprocess
import pyperclip

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.llm_client import call_llm

load_dotenv()
base_url = os.environ.get("LLM_BASE_URL")
api_key = os.environ.get("LLM_API_KEY")
model = os.environ.get("LLM_MODEL")


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


def git_command(command: list[str]):
    result = subprocess.run(
        ["git"] + command,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return result.stdout


if __name__ == "__main__":
    prompt = COMMIT_MESSAGE_PROMPT.format(
        diff_cached=git_command(["diff", "--cached"]),
        diff=git_command(["diff"]),
        status=git_command(["status"]),
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

