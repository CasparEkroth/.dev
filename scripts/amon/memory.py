import json
from uuid import UUID, uuid4
from pathlib import Path
from config import SESSIONS_DIR


def save_session(
    conversation: list[dict],
    session_id: UUID = None,
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


def save_context_tokens(
    session_id: UUID, tokens: int, session_dir: Path = SESSIONS_DIR
) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    _meta_path(session_id, session_dir).write_text(
        json.dumps({"context_tokens": tokens}), encoding="utf-8"
    )


def load_context_tokens(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> int:
    path = _meta_path(session_id, session_dir)
    if not path.exists():
        return 0
    return json.loads(path.read_text(encoding="utf-8")).get("context_tokens", 0)


def get_list_of_sessions(
    session_dir: Path = SESSIONS_DIR,
) -> list[tuple(UUID, float)]:
    if not session_dir.exists():
        return []
    return [
        (p, p.stat().st_mtime)
        for p in session_dir.iterdir()
        if not p.name.endswith(".meta.json")
    ]


def remove_session(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> bool:
    path = session_dir / str(session_id)
    _meta_path(session_id, session_dir).unlink(missing_ok=True)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def clear_sessions(keep_conut: int = 5) -> list[tuple(Path, float)]:
    sessions = get_list_of_sessions()
    sessions.sort(key=lambda x: x[1], reverse=True)
    rm_ses = sessions[keep_conut:]
    for s in rm_ses:
        remove_session(s[0].name)
    return rm_ses
