import json
from uuid import UUID, uuid4
from pathlib import Path
import os

SESSIONS_DIR = Path("sessions/")


def save_session(
    conversation: list[dict],
    session_id: UUID = None,
    session_dir: Path = SESSIONS_DIR,
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

    existing.extend(conversation)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return session_id


def load_session(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> list[dict]:
    path = session_dir / str(session_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def get_list_of_sessions(
    session_dir: Path = SESSIONS_DIR,
) -> list[(UUID, float)]:
    return [(p, p.stat().st_mtime) for p in session_dir.iterdir()]


def remove_session(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> bool:
    path = session_dir / str(session_id)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
