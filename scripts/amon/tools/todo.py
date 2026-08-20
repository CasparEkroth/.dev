"""In-memory checklist tool so an agent can track a multi-step task."""

_VALID_STATUSES = {"pending", "in_progress", "completed"}
_STATUS_MARK = {"pending": "○", "in_progress": "◐", "completed": "✓"}

#: session id (str) -> list of {"content", "status"}.
_TODOS: dict[str, list[dict]] = {}


def render_todos(todos: list[dict]) -> str:
    """Render a checklist as a human/model-readable string."""
    if not todos:
        return "Todo list is empty."
    return "\n".join(
        f"{_STATUS_MARK.get(t['status'], '?')} [{t['status']}] {t['content']}"
        for t in todos
    )


def write_todos(todos: list[dict], session_id: str | None = None) -> str:
    """Replace the checklist for *session_id* and return it rendered.

    Each item needs a non-empty ``content`` and a ``status`` in
    ``pending``/``in_progress``/``completed``; a bad item is reported as its
    own line and dropped rather than failing the whole call, matching
    ``write_file``'s per-item status-line style. More than one
    ``in_progress`` item is let through with a note rather than rejected —
    advisory, not a hard rule.
    """
    key = session_id or "default"
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

    _TODOS[key] = clean

    if in_progress_count > 1:
        notes.append(
            f"note: {in_progress_count} items are 'in_progress' — usually "
            "only one should be at a time."
        )
    notes.append(render_todos(clean))
    return "\n".join(notes)


def get_todos(session_id: str | None = None) -> list[dict]:
    """Read back the current checklist for *session_id* (a copy)."""
    return list(_TODOS.get(session_id or "default", []))
