from pathlib import Path
import time


def format_sessions(sessions: list[tuple[Path, float]]) -> str:
    if not sessions:
        return "No sessions found."
    lines = []
    for idx, (path, ts) in enumerate(sessions):
        lines.append(f"- **{idx}** | `{path.name}` | {time.ctime(ts)}")
    return "\n".join(lines)
