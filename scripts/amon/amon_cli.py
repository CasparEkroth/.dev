import argparse
import asyncio
import json
import os
import sys
from uuid import UUID, uuid4

from config import settings
from scripts.amon.tools.agent import run_jobs
from scripts.amon.tools.registry import (
    _AGENT_DESCRIPTION_STR,
    get_registry,
    READY_AGENTS,
)
from scripts.amon.agent_loop import _compact_history, file_event_log, run_agent
from scripts.amon import terminal
from scripts.amon.memory import (
    clear_sessions,
    get_list_of_sessions,
    load_context_tokens,
    load_session,
    remove_session,
    save_session,
)
from shared.llm_client import get_context_window

from scripts.amon.tools.skills import catalog_for_agent


def _init_context_limit() -> None:
    limit = get_context_window(
        settings.LLM_BASE_URL,
        settings.LLM_API_KEY,
        settings.LLM_MODEL,
        provider=settings.LLM_PROVIDER,
    )
    if limit:
        terminal.set_context_limit(limit)


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


def _run_interactive(args) -> None:
    session_id = _resolve_session_id(args)
    if session_id is None:
        return

    terminal.update_footer(context=load_context_tokens(session_id))
    terminal.show_welcome(session_id)
    prompt_session = terminal.make_prompt_session()
    agent = READY_AGENTS.get(args.agent, None)

    if agent is None:
        terminal.console.print(f"Error: {args.agent} is not a saved agent")
        return

    while True:
        try:
            user_input = prompt_session.prompt("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            terminal.console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        if user_input in ("/exit", "/quit", "/q"):
            terminal.console.print("[dim]Goodbye.[/dim]")
            break

        if user_input == ("/agent"):
            t_agent = terminal.pick_agents()
            if t_agent is None or t_agent == "[cancel]":
                terminal.console.print("[dim]No agent picked.[/dim]")
                terminal.console.print(f"[dim]Current agent: {agent.name}")
                continue
            agent = READY_AGENTS.get(t_agent)
            continue

        if user_input == "/sessions":
            terminal.print_sessions(_sorted_sessions())
            continue

        if user_input == "/new":
            session_id = uuid4()
            terminal.reset_context()
            terminal.console.print("[dim]New session started.[/dim]")
            continue

        if user_input == "/compact":
            conversation = load_session(session_id)
            if not conversation:
                terminal.console.print("[dim]Session is empty.[/dim]")
                continue
            # Same path the auto-compactor uses: strips any dangling
            # tool_calls first and only summarizes the safe head, keeping the
            # most recent complete tool cycle verbatim — the plain
            # compact_conversation() call this replaced had neither
            # protection and could silently drop in-flight tool state.
            with terminal.spinner_context():
                ok = _compact_history(conversation)
            if not ok:
                terminal.console.print(
                    "[red]Compact failed: model did not return valid JSON.[/red]"
                )
                continue
            save_session(
                conversation=conversation,
                session_id=session_id,
                override=True,
            )
            terminal.console.print("[dim]Session compacted.[/dim]")
            terminal.update_footer(context="-")
            continue

        if str(user_input).startswith("/"):
            terminal.console.print(
                f"[dim]{user_input.split()[0]} is not a command.[/dim]"
            )
            continue

        with terminal.spinner_context():
            try:
                result = run_agent(
                    system_prompt=agent.system_prompt,
                    user_input=user_input,
                    tool_registry=get_registry(
                        tools=agent.tools,
                        allowed_tools=agent.allowed_tools,
                        allow_paths=agent.allow_paths,
                        deny_paths=agent.deny_paths,
                        denied_commands=agent.denied_commands,
                        session_id=session_id,
                    ),
                    skill_catalog=catalog_for_agent(agent.allowed_skills),
                    confirm_fn=terminal.confirm_tool,
                    stream_actions=terminal.stream_action,
                    token_fn=terminal.update_footer,
                    session_id=session_id,
                    save_session_=True,
                    hooks=agent.hooks,
                    max_turns=agent.max_turns,
                    force_first_tool=agent.force_first_tool,
                    max_runtime_s=agent.max_runtime_s,
                    model=agent.model,
                    system_prompt_template=agent.system_prompt_template,
                    max_tool_output_chars=agent.max_tool_output_chars,
                    agent_name=agent.name,
                    event_log=file_event_log if os.environ.get("AMON_EVENTS") else None,
                )
            except KeyboardInterrupt:
                # Hard cancel: in-flight HTTP is aborted; no delayed receive.
                # ESC is not handled — only Ctrl+C raises KeyboardInterrupt.
                terminal.console.print("\n[yellow]Interrupted.[/yellow]")
                continue

            # Clear the live checklist once the task is actually done — a
            # failed/interrupted run keeps it, since the leftover state (e.g.
            # what was still 'in_progress') is useful context for why it
            # stopped there. Only a clean finish resets the footer.
            if result.ok:
                terminal.footer.reset_footer(todos=True)

            # Streaming already showed content; surface structured failure meta.
            if not result.ok:
                err = result.error or "Agent run failed."
                terminal.console.print(f"[red]{err}[/red]")
                meta_parts = []
                if result.usage.get("total_tokens"):
                    meta_parts.append(f"tokens={result.usage['total_tokens']}")
                if result.turns:
                    meta_parts.append(f"turns={result.turns}")
                if result.tools_used:
                    meta_parts.append(f"tools={', '.join(result.tools_used)}")
                if meta_parts:
                    terminal.console.print(f"[dim]{' · '.join(meta_parts)}[/dim]")


def _resolve_session_id(args) -> UUID | None:
    if args.resume_id:
        return args.resume_id
    if args.resume:
        sessions = _sorted_sessions()
        picked = terminal.pick_session(sessions)
        if picked == "[cancel]" or picked is None:
            return None
        return UUID(picked.name)
    return uuid4()


def _sorted_sessions():
    sessions = get_list_of_sessions()
    sessions.sort(key=lambda x: x[1], reverse=True)
    return sessions


def _headless_payload(results: list[dict]) -> dict:
    """Normalize spawn_agents output for CLI --json consumers."""
    if len(results) == 1:
        return results[0]
    return {
        "ok": all(bool(r.get("ok")) for r in results),
        "results": results,
    }


if __name__ == "__main__":
    main()
