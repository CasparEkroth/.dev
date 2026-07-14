import argparse
from uuid import UUID, uuid4

from scripts.amon.agent_loop import run_agent
from scripts.amon.tools.registry import tool_registry
from scripts.amon import terminal
from scripts.amon.memory import get_list_of_sessions, remove_session
from scripts.amon.tools.skills import skill_catalog

SYSTEM_PROMPT = "you are a coding agent"


def main() -> None:
    parser = argparse.ArgumentParser(prog="amon")

    command = parser.add_mutually_exclusive_group()
    command.add_argument(
        "--resume", "-r", action="store_true", help="Resume the last session"
    )
    command.add_argument("--resume-id", type=UUID, help="Resume session by ID")
    command.add_argument("--list-sessions", action="store_true", help="List sessions")
    command.add_argument("--delete-session", type=UUID, help="Delete session by ID")
    command.add_argument(
        "--headless", type=str, metavar="INPUT", help="Run in headless mode"
    )

    parser.add_argument("--agent-type", type=str, default="default")
    parser.add_argument("--save-session", action="store_true")

    args = parser.parse_args()

    if args.list_sessions:
        sessions = _sorted_sessions()
        terminal.print_sessions(sessions)
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

    if args.headless:
        with terminal.spinner_context():
            result = run_agent(
                system_prompt=SYSTEM_PROMPT,
                user_input=args.headless,
                tool_registry=tool_registry,
                skill_catalog=skill_catalog,
                confirm_fn=terminal.confirm_tool,
                save_session_=args.save_session,
                headless=True,
            )
        terminal.print_response(result)
        return

    _run_interactive(args)


def _run_interactive(args) -> None:
    session_id = _resolve_session_id(args)
    if session_id is None:
        return

    terminal.show_welcome(session_id)
    prompt_session = terminal.make_prompt_session()

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

        if user_input == "/sessions":
            terminal.print_sessions(_sorted_sessions())
            continue

        if user_input == "/new":
            session_id = uuid4()
            terminal.console.print("[dim]New session started.[/dim]")
            continue

        if str(user_input).startswith("/"):
            terminal.console.print(
                f"[dim]{user_input.split()[0]} is not a command.[/dim]"
            )
            continue

        with terminal.spinner_context():
            result = run_agent(
                system_prompt=SYSTEM_PROMPT,
                user_input=user_input,
                tool_registry=tool_registry,
                skill_catalog=skill_catalog,
                confirm_fn=terminal.confirm_tool,
                session_id=session_id,
                save_session_=True,
            )

        terminal.print_response(result)


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


if __name__ == "__main__":
    main()
