"""CLI entry for `amon`: argparse, headless mode, session management flags."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from uuid import UUID

from config import settings
from scripts.amon.tools.agent import run_jobs
from scripts.amon.tools.registry import _AGENT_DESCRIPTION_STR
from scripts.amon import terminal
from scripts.amon.cli_interactive import (  # noqa: F401 — re-export for tests
    _close_mcp,
    _discover_agent_mcp_tools,
    _resolve_session_id,
    _run_agent_cancelable,
    _run_interactive,
    _sorted_sessions,
)
from scripts.amon.memory import (
    clear_sessions,
    remove_session,
)
from shared.llm_client import get_context_window


def _init_context_limit() -> None:
    limit = get_context_window(
        settings.LLM_BASE_URL,
        settings.LLM_API_KEY,
        settings.LLM_MODEL,
        provider=settings.LLM_PROVIDER,
    )
    if limit:
        terminal.set_context_limit(limit)


def _headless_payload(results: list[dict]) -> dict:
    """Normalize spawn_agents output for CLI --json consumers."""
    if len(results) == 1:
        return results[0]
    return {
        "ok": all(bool(r.get("ok")) for r in results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="amon")

    command = parser.add_mutually_exclusive_group()
    command.add_argument(
        "--resume", "-r", action="store_true", help="Resume the last session"
    )
    command.add_argument("--resume-id", type=UUID, help="Resume session by ID")
    command.add_argument("--list-sessions", action="store_true", help="List sessions")
    command.add_argument("--list-agents", action="store_true", help="List agents")
    command.add_argument("--delete-session", type=UUID, help="Delete session by ID")
    command.add_argument(
        "--keep-N-sessions",
        "-keep",
        type=int,
        help="Keeps only the N latest sessions",
    )
    command.add_argument(
        "--headless", type=str, metavar="INPUT", help="Run in headless mode"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Headless only: print the result as JSON on stdout",
    )
    parser.add_argument("--agent", type=str, default="default")

    parser.add_argument("--save-session", action="store_true")
    parser.add_argument(
        "--session-id",
        type=UUID,
        help="Headless only: use this session id (resume if it exists)",
    )
    parser.add_argument(
        "--model", type=str, default=None, help="Headless only: override agent model"
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Headless only: override agent max turns",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Headless only: stream tool calls/results to stderr",
    )

    args = parser.parse_args()

    if args.json and not args.headless:
        parser.error("--json requires --headless")

    if (
        args.list_sessions
        or args.delete_session
        or args.keep_N_sessions
        or args.list_agents
    ):
        if args.save_session or args.json or args.agent != "default":
            parser.error(
                "session management flags can't be combined with "
                "--agent/--save-session/--json"
            )

    if args.save_session and not args.headless:
        parser.error("--save-session requires --headless")
    if args.session_id is not None and not args.headless:
        parser.error("--session-id requires --headless")
    if args.model is not None and not args.headless:
        parser.error("--model requires --headless")
    if args.max_turns is not None and not args.headless:
        parser.error("--max-turns requires --headless")
    if args.stream and not args.headless:
        parser.error("--stream requires --headless")
    if args.stream:
        os.environ["AMON_STREAM"] = "1"

    if args.list_sessions:
        sessions = _sorted_sessions()
        terminal.print_sessions(sessions)
        return

    if args.list_agents:
        terminal.console.print(_AGENT_DESCRIPTION_STR)
        return

    if args.delete_session:
        if remove_session(args.delete_session):
            terminal.console.print(
                f"[green]Deleted session {args.delete_session}[/green]"
            )
        else:
            terminal.console.print(
                f"[red]Session {args.delete_session} not found.[/red]"
            )
        return

    if args.keep_N_sessions:
        rm_ses = clear_sessions(args.keep_N_sessions)
        if rm_ses:
            names = "\n".join(s[0].name for s in rm_ses)
            terminal.console.print(f"[green]Deleted sessions:\n{names}")
        else:
            terminal.console.print("[yellow]No sessions to delete.")
        return

    _init_context_limit()

    if args.headless:
        try:
            # --json: spinner on stderr so stdout stays pipe-clean.
            # pretty headless: spinner on stdout with the result panels.
            with terminal.spinner_context(stderr=bool(args.json)):
                job = {
                    "agent": args.agent,
                    "task": args.headless,
                    "save_session": args.save_session,
                }
                if args.session_id is not None:
                    job["session_id"] = args.session_id
                if args.model is not None:
                    job["model"] = args.model
                if args.max_turns is not None:
                    job["max_turns"] = args.max_turns
                results = asyncio.run(run_jobs([job]))
        except Exception as e:
            results = [
                {
                    "ok": False,
                    "agent": args.agent,
                    "task": args.headless,
                    "result": None,
                    "error": str(e),
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "turns": 0,
                    "tools_used": [],
                    "session_id": None,
                }
            ]

        payload = _headless_payload(results)
        if args.json:
            json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
            sys.exit(0 if payload.get("ok") else 1)
        else:
            terminal.print_headless_result(results)
            if not payload.get("ok"):
                sys.exit(1)
        return

    _run_interactive(args)


if __name__ == "__main__":
    main()
