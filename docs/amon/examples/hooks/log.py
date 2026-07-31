#!/usr/bin/env python3
"""Example amon hook (Python). Same data as examples/hooks/log.sh."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def main() -> None:
    cwd = os.environ.get("CWD", ".")
    log_path = Path(cwd) / "agent.log"
    lines = [
        "========== hook log ==========",
        f"timestamp       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"SESSION_ID      : {os.environ.get('SESSION_ID', '')}",
        f"HOOK_EVENT_NAME : {os.environ.get('HOOK_EVENT_NAME', '')}",
        f"CWD             : {os.environ.get('CWD', '')}",
        f"PROMPT          : {os.environ.get('PROMPT', '')}",
        f"RESPONSE        : {os.environ.get('RESPONSE', '')}",
        f"TOOL_NAME       : {os.environ.get('TOOL_NAME', '')}",
        f"TOOL_INPUT      : {os.environ.get('TOOL_INPUT', '')}",
        f"TOOL_OUTPUT     : {os.environ.get('TOOL_OUTPUT', '')}",
        "================================",
        "",
    ]
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
