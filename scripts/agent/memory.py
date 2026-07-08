import json
from uuid import UUID, uuid4
import os
from pathlib import Path

SESSIONS_DIR = Path("sessions/")


def save_conversation(
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


def load_conversation(session_id: UUID, session_dir: Path = SESSIONS_DIR) -> list[dict]:
    path = session_dir / str(session_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
