import argparse
from uuid import UUID, uuid4


from config import settings
from scripts.amon.tools.agent import spawn_agents
from scripts.amon.tools.registry import get_registry, READY_AGENTS
from scripts.amon.agent_loop import run_agent
from scripts.amon import terminal
from scripts.amon.memory import (
    clear_sessions,
    get_list_of_sessions,
    load_context_tokens,
    load_session,
    remove_session,
    save_session,
)
from shared.llm_client import call_llm, get_context_window, parse_llm_json
import asyncio

from scripts.amon.tools.skills import catalog_for_agent


def _init_context_limit() -> None:
    limit = get_context_window(
        settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL
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
    command.add_argument("--delete-session", type=UUID, help="Delete session by ID")
    command.add_argument(
        "--keep-N-sessions",
        "-keep-n",
        type=int,
        help="Keeps only the N latest sessions",
    )
    command.add_argument(
        "--headless", type=str, metavar="INPUT", help="Run in headless mode"
    )

    parser.add_argument("--agent", type=str, default="default")
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
        with terminal.spinner_context():
            result = asyncio.run(
                spawn_agents([{"agent": args.agent, "task": args.headless}])
            )
        terminal.print_headless_result(result)
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
                terminal.console.print("[dim]No agent picket.[/dim]")
                terminal.console.print(f"[dim]Current agent: {agent.name}")
                continue
            agent = READY_AGENTS.get(t_agent)
            continue

        if user_input == "/sessions":
            terminal.print_sessions(_sorted_sessions())
            continue

        if user_input == "/new":
            session_id = uuid4()
            terminal.reste_context()
            terminal.console.print("[dim]New session started.[/dim]")
            continue

        if user_input == "/compact":
            conversation = load_session(session_id)
            if not conversation:
                terminal.console.print("[dim]Session is empty.[/dim]")
                continue
            with terminal.spinner_context():
                response = call_llm(
                    f"summarize this conversation {conversation} return the summary as a json in the same structure as the original but significant smaller."
                )
            new_conversation = parse_llm_json(response)
            if new_conversation is None:
                terminal.console.print(
                    "[red]Compact failed: model did not return valid JSON.[/red]"
                )
                continue
            save_session(
                conversation=new_conversation,
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
            run_agent(
                system_prompt=agent.system_prompt,
                user_input=user_input,
                tool_registry=get_registry(
                    tools=agent.tools, allowed_tools=agent.allowed_tools
                ),
                skill_catalog=catalog_for_agent(agent.allowed_skills),
                confirm_fn=terminal.confirm_tool,
                stream_actions=terminal.stream_action,
                token_fn=terminal.update_footer,
                session_id=session_id,
                save_session_=True,
                hooks=agent.hooks,
            )

        # terminal.print_response(result)


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
