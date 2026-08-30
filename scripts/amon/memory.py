import json
from uuid import UUID, uuid4
from pathlib import Path
from config import SESSIONS_DIR


def save_session(
    conversation: list[dict],
    session_id: UUID | None = None,
    session_dir: Path = SESSIONS_DIR,
    override: bool = False,
) -> UUID:
    if conversation is None:
        return session_id or uuid4()

    session_dir.mkdir(parents=True, exist_ok=True)
    if session_id is None:
        session_id = uuid4()

    path = session_dir / str(session_id)
    existing = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    if override:
        existing = conversation
    else:
        existing.extend(conversation)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return session_id


def load_session(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> list[dict]:
    path = session_dir / str(session_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _meta_path(session_id: UUID, session_dir: Path) -> Path:
    return session_dir / f"{session_id}.meta.json"


def _load_meta(session_id: UUID, session_dir: Path) -> dict:
    path = _meta_path(session_id, session_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _update_meta(session_id: UUID, session_dir: Path, **fields) -> None:
    """Merge *fields* into the session's .meta.json (dropping ``None`` values).

    A plain overwrite would have clobbered whichever of context_tokens /
    agent / preview wasn't being set by this particular call.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    meta = _load_meta(session_id, session_dir)
    meta.update({k: v for k, v in fields.items() if v is not None})
    _meta_path(session_id, session_dir).write_text(json.dumps(meta), encoding="utf-8")


def save_context_tokens(
    session_id: UUID, tokens: int, session_dir: Path = SESSIONS_DIR
) -> None:
    _update_meta(session_id, session_dir, context_tokens=tokens)


def load_context_tokens(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> int:
    return _load_meta(session_id, session_dir).get("context_tokens", 0)


def save_session_info(
    session_id: UUID,
    session_dir: Path = SESSIONS_DIR,
    *,
    agent: str | None = None,
    preview: str | None = None,
) -> None:
    """Record which agent ran this session and a short preview of its first
    task, for `/sessions` and the `--resume` picker. Resuming used to be a
    guess from a bare UUID and a timestamp.
    """
    _update_meta(session_id, session_dir, agent=agent, preview=preview)


def load_session_info(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> dict:
    meta = _load_meta(session_id, session_dir)
    return {"agent": meta.get("agent"), "preview": meta.get("preview")}


def _todos_path(session_id: UUID | str, session_dir: Path) -> Path:
    return session_dir / f"{session_id}.todos.json"


def save_todos(
    session_id: UUID | str, todos: list[dict], session_dir: Path = SESSIONS_DIR
) -> None:
    """Persist *todos* for *session_id* alongside its session transcript.

    Sidecar file (like `.meta.json`), so it survives `--resume` and is
    visible to `spawn_agents` children given the same session id — those are
    separate processes and can't share an in-memory store.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    _todos_path(session_id, session_dir).write_text(
        json.dumps(todos, indent=2), encoding="utf-8"
    )


def load_todos(session_id: UUID | str, session_dir: Path = SESSIONS_DIR) -> list[dict]:
    path = _todos_path(session_id, session_dir)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _events_path(session_id: UUID | str, session_dir: Path) -> Path:
    return session_dir / f"{session_id}.events.jsonl"


def append_event(
    session_id: UUID | str, event: dict, session_dir: Path = SESSIONS_DIR
) -> None:
    """Append one JSONL line to the session's optional event log.

    Opt-in observability (see `AMON_EVENTS` in agent_loop.py) — turn
    latency, tool latency, compaction triggers. Off by default: every call
    site is gated behind the env var before this ever runs, so a normal run
    pays no cost.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    with open(_events_path(session_id, session_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _is_session_file(p: Path) -> bool:
    """A session transcript's filename is exactly its UUID — nothing else."""
    if (
        p.name.endswith(".meta.json")
        or p.name.endswith(".todos.json")
        or p.name.endswith(".events.jsonl")
    ):
        return False
    try:
        UUID(p.name)
    except ValueError:
        return False
    return True


def get_list_of_sessions(
    session_dir: Path = SESSIONS_DIR,
) -> list[tuple[Path, float]]:
    if not session_dir.exists():
        return []
    return [
        (p, p.stat().st_mtime) for p in session_dir.iterdir() if _is_session_file(p)
    ]


def remove_session(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> bool:
    path = session_dir / str(session_id)
    _meta_path(session_id, session_dir).unlink(missing_ok=True)
    _todos_path(session_id, session_dir).unlink(missing_ok=True)
    _events_path(session_id, session_dir).unlink(missing_ok=True)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def clear_sessions(keep_count: int = 5) -> list[tuple[Path, float]]:
    sessions = get_list_of_sessions()
    sessions.sort(key=lambda x: x[1], reverse=True)
    rm_ses = sessions[keep_count:]
    for s in rm_ses:
        remove_session(s[0].name)
    return rm_ses
