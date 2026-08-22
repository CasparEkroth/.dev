"""Checklist tool so an agent can track a multi-step task.

Persisted per session (Phase 2 of TASK_TRACKING_PLAN.md): when a session id
is given, the checklist is written to the same SESSIONS_DIR as the session
transcript (via `scripts.amon.memory`), so it survives `--resume` and is
visible to `spawn_agents` children given the same session id — those are
separate processes, so the disk file (not the fallback store below) is what
makes that work. A run with no session id (e.g. an ephemeral headless call
with no `--session-id`) falls back to an in-memory, per-process store.
"""

from pathlib import Path

from config import SESSIONS_DIR
from scripts.amon.memory import load_todos, save_todos

_VALID_STATUSES = {"pending", "in_progress", "completed"}
_STATUS_MARK = {"pending": "○", "in_progress": "◐", "completed": "✓"}

#: Fallback store for runs with no session id to persist against.
_EPHEMERAL_TODOS: dict[str, list[dict]] = {}


def render_todos(todos: list[dict]) -> str:
    """Render a checklist as a human/model-readable string."""
    if not todos:
        return "Todo list is empty."
    return "\n".join(
        f"{_STATUS_MARK.get(t['status'], '?')} [{t['status']}] {t['content']}"
        for t in todos
    )


def write_todos(
    todos: list[dict],
    session_id: str | None = None,
    session_dir: Path = SESSIONS_DIR,
) -> str:
    """Replace the checklist for *session_id* and return it rendered.

    Each item needs a non-empty ``content`` and a ``status`` in
    ``pending``/``in_progress``/``completed``; a bad item is reported as its
    own line and dropped rather than failing the whole call, matching
    ``write_file``'s per-item status-line style. More than one
    ``in_progress`` item is let through with a note rather than rejected —
    advisory, not a hard rule.
    """
    clean: list[dict] = []
    notes: list[str] = []
    in_progress_count = 0

    for i, item in enumerate(todos):
        content = str(item.get("content") or "").strip()
        status = item.get("status")
        if not content:
            notes.append(f"item {i}: missing 'content', skipped")
            continue
        if status not in _VALID_STATUSES:
            notes.append(
                f"item {i} ({content!r}): invalid status {status!r}, must be "
                f"one of {sorted(_VALID_STATUSES)}, skipped"
            )
            continue
        if status == "in_progress":
            in_progress_count += 1
        clean.append({"content": content, "status": status})

    if session_id:
        save_todos(session_id, clean, session_dir=session_dir)
    else:
        _EPHEMERAL_TODOS["default"] = clean

    if in_progress_count > 1:
        notes.append(
            f"note: {in_progress_count} items are 'in_progress' — usually "
            "only one should be at a time."
        )
    notes.append(render_todos(clean))
    return "\n".join(notes)


def get_todos(
    session_id: str | None = None, session_dir: Path = SESSIONS_DIR
) -> list[dict]:
    """Read back the current checklist for *session_id* (a copy)."""
    if session_id:
        return load_todos(session_id, session_dir=session_dir)
    return list(_EPHEMERAL_TODOS.get("default", []))
