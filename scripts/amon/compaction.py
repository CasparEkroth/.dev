"""Conversation compaction: summarize or hard-trim history to free context.

Used by the agent loop (auto-compact on token threshold / model failures) and
by the interactive `/compact` command. Public entry points keep the same
names they had when they lived in ``agent_loop`` so existing patches and
imports continue to work via re-exports there.
"""

from __future__ import annotations

from shared.llm_client import call_llm, parse_llm_json


def _is_context_length_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "context_length_exceeded" in text or "exceed the configured limit" in text


def _normalize_message(msg: dict) -> dict:
    """Keep role/content only — strips tool_calls and other extras for summaries."""
    return {
        "role": msg.get("role"),
        "content": str(msg.get("content") or ""),
    }


def _trim_for_summary(conversation: list[dict], limit: int = 24) -> list[dict]:
    if len(conversation) <= limit:
        return [_normalize_message(m) for m in conversation]
    head = conversation[: max(4, limit // 3)]
    tail = conversation[-max(8, (limit * 2) // 3) :]
    return [
        _normalize_message(m)
        for m in head
        + [
            {
                "role": "user",
                "content": "[... earlier conversation omitted for compaction ...]",
            }
        ]
        + tail
    ]


def compact_conversation(conversation: list[dict]) -> dict | None:
    """Summarize *conversation* into a small structured object, or None on failure.

    Uses bounded input first so compaction itself can recover from oversized
    histories. Falls back to a deterministic hard trim if the model still
    refuses because of context length.
    """
    if not conversation:
        return None

    candidate = _trim_for_summary(conversation)
    prompt = (
        "Summarize this conversation into a JSON object with exactly these "
        'keys: "goal" (string — the user\'s overall objective), "done" '
        "(array of strings — what has been completed so far), "
        '"open_questions" (array of strings — unresolved questions or '
        'decisions), "key_paths" (array of strings — file paths or '
        "resources touched that still matter). Return only valid JSON. "
        f"Conversation:\n{candidate}"
    )

    try:
        parsed = parse_llm_json(call_llm(prompt))
    except Exception as exc:  # noqa: BLE001
        if not _is_context_length_error(exc):
            return None
        parsed = None

    if not isinstance(parsed, dict):
        return None

    summary = {
        "goal": str(parsed.get("goal") or "").strip(),
        "done": [str(x) for x in parsed.get("done") or [] if str(x).strip()],
        "open_questions": [
            str(x) for x in parsed.get("open_questions") or [] if str(x).strip()
        ],
        "key_paths": [str(x) for x in parsed.get("key_paths") or [] if str(x).strip()],
    }
    if not any(summary.values()):
        return None
    return summary


def _render_compact_summary(summary: dict) -> str:
    """Render a structured compact summary into a single message body."""
    lines = ["[Earlier conversation summarized]"]
    if summary.get("goal"):
        lines.append(f"Goal: {summary['goal']}")
    for label, key in (
        ("Done", "done"),
        ("Open questions", "open_questions"),
        ("Key paths", "key_paths"),
    ):
        items = summary.get(key) or []
        if items:
            lines.append(f"{label}:")
            lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _strip_unfinished_tool_turns(conversation: list[dict]) -> list[dict]:
    clean = list(conversation)
    while True:
        last_assistant = next(
            (
                i
                for i in range(len(clean) - 1, -1, -1)
                if clean[i].get("role") == "assistant" and clean[i].get("tool_calls")
            ),
            None,
        )
        if last_assistant is None:
            return clean
        tool_ids = [
            c.get("id")
            for c in clean[last_assistant].get("tool_calls", [])
            if c.get("id")
        ]
        if not tool_ids:
            clean = clean[:last_assistant]
            continue
        seen = {tool_id: False for tool_id in tool_ids}
        for msg in clean[last_assistant + 1 :]:
            if msg.get("role") == "tool" and msg.get("tool_call_id") in seen:
                seen[msg.get("tool_call_id")] = True
        if all(seen.values()):
            return clean
        clean = clean[:last_assistant]


def _compaction_plan(conversation: list[dict]) -> tuple[list[dict], int] | None:
    """Return (safe, cut): safe is *conversation* with unfinished tool turns
    stripped, cut is the index up to which it could be summarized. None means
    there's nothing worth compacting — e.g. only the current, unanswered user
    message survives stripping — distinct from "the model call failed."
    """
    safe = _strip_unfinished_tool_turns(conversation)
    if not safe:
        return None
    cut = next(
        (
            i
            for i in range(len(safe) - 1, -1, -1)
            if safe[i].get("role") == "assistant" and safe[i].get("tool_calls")
        ),
        len(safe),
    )
    # A trailing, not-yet-answered user message is the current task, not
    # history — never let it get folded into the summary.
    if safe[-1].get("role") == "user":
        cut = min(cut, len(safe) - 1)
    if cut <= 0:
        return None
    return safe, cut


def _compact_history(conversation: list[dict]) -> bool:
    """Summarize *conversation* in place, preserving only complete tool cycles
    and the current user task's own text.

    Returns False when the summary was unusable (or there was nothing left
    worth summarizing) and nothing changed.
    """
    plan = _compaction_plan(conversation)
    if plan is None:
        return False
    safe, cut = plan
    summary = compact_conversation(safe[:cut])
    if not summary:
        return False
    summary_message = {"role": "user", "content": _render_compact_summary(summary)}
    conversation[:] = [summary_message] + safe[cut:]
    return True


def _force_hard_trim(conversation: list[dict], keep: int = 12) -> bool:
    if len(conversation) <= keep:
        return False
    prefix = [m for m in conversation[:-keep] if m.get("role") == "system"][:1]
    suffix = [_normalize_message(m) for m in conversation[-keep:]]
    conversation[:] = (
        prefix
        + [
            {
                "role": "user",
                "content": "[conversation truncated to preserve context window]",
            }
        ]
        + suffix
    )
    return True
