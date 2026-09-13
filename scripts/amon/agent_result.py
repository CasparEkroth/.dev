"""Agent run result type, usage helpers, tool-output truncation, event log."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from config import MAX_TOOL_OUTPUT_CHARS, TOOL_OUTPUT_DIR
from scripts.amon.memory import append_event


def truncate_tool_output(
    text: str,
    tool: str = "",
    session_id: UUID | str | None = None,
    limit: int = MAX_TOOL_OUTPUT_CHARS,
    spill_dir: Path = TOOL_OUTPUT_DIR,
) -> str:
    """Cap one tool result at *limit*, keeping its head and tail.

    The full text is written to *spill_dir* and the marker names that file, so
    one verbose command cannot exhaust the context window and nothing is lost.
    """
    if len(text) <= limit:
        return text

    spill_dir.mkdir(parents=True, exist_ok=True)
    spill = (
        spill_dir
        / f"{session_id or 'nosession'}_{tool or 'tool'}_{uuid4().hex[:8]}.txt"
    )
    spill.write_text(text, encoding="utf-8")

    head_len = limit * 6 // 10
    tail_len = limit - head_len
    marker = (
        f"\n… [truncated {len(text) - limit} of {len(text)} chars — "
        f"full output: {spill} (read it with read_file)] …\n"
    )
    return f"{text[:head_len]}{marker}{text[-tail_len:]}"


@dataclass
class AgentResult:
    """Structured result returned by run_agent."""

    ok: bool
    result: str | None
    error: str | None = None
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )
    turns: int = 0
    tools_used: list[str] = field(default_factory=list)
    session_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "usage": dict(self.usage),
            "turns": self.turns,
            "tools_used": list(self.tools_used),
            "session_id": self.session_id,
        }


def file_event_log(event: dict) -> None:
    """Default `event_log` sink: append to `{session_id}.events.jsonl`.

    Callers gate this behind `AMON_EVENTS` (same pattern `AMON_STREAM` uses
    for `stream_action_stderr`) — an event with no session_id (an ephemeral
    run with nothing to attach it to) is silently dropped rather than
    raised, since there's nowhere sensible to write it.
    """
    session_id = event.get("session_id")
    if session_id:
        append_event(session_id, event)


def _preview(text: str, limit: int = 60) -> str:
    """First line of *text*, collapsed and capped, for session listings."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _turn_usage(raw: dict | None) -> dict[str, int]:
    """Normalize one LLM response usage blob."""
    raw = raw or {}
    prompt = int(raw.get("prompt_tokens") or 0)
    completion = int(raw.get("completion_tokens") or 0)
    total = int(raw.get("total_tokens") or (prompt + completion) or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _add_usage(acc: dict[str, int], turn: dict[str, int]) -> dict[str, int]:
    """Accumulate usage across turns (full-run totals)."""
    return {
        "prompt_tokens": acc["prompt_tokens"] + turn["prompt_tokens"],
        "completion_tokens": acc["completion_tokens"] + turn["completion_tokens"],
        "total_tokens": acc["total_tokens"] + turn["total_tokens"],
    }
