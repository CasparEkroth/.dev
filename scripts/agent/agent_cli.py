from scripts.agent.agent_loop import run_agent
from scripts.agent.tools.registry import tool_registry
import argparse
from uuid import UUID
from rich.console import Console
from rich.markdown import Markdown
from scripts.agent.memory import (
    load_session,
    get_list_of_sessions,
    remove_session,
    SESSIONS_DIR,
)
from shared.file_handler import scan_folder
from scripts.agent.ui import format_sessions


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent")

    command = parser.add_mutually_exclusive_group()

    command.add_argument("--resume", help="Resumes the last open session")
    command.add_argument("--resume-id", type=UUID, help="Resumes session on id")
    command.add_argument(
        "--list-sessions",
        default=False,
        action="store_true",
        help="show list of sessions",
    )
    command.add_argument("--delete-session", type=UUID, help="Delete session on id")
    command.add_argument(
        "--headless", type=str, metavar="INPUT", help="Run the agent in headless mode"
    )

    # Add sub-flags that work with --headless
    parser.add_argument(
        "--agent-type",
        type=str,
        default="default",
        help="Type of agent to use (e.g., coding, research)",
    )
    parser.add_argument(
        "--save-session",
        default=False,
        action="store_true",
        help="Save the session after completion",
    )

    args = parser.parse_args()
    console = Console()

    if args.list_sessions:
        sessions = get_list_of_sessions()
        sessions.sort(key=lambda x: x[1], reverse=True)
        string = format_sessions(sessions)
        console.print(Markdown(string))

    if args.headless:
        r = run_agent(
            system_prompt="you are a coding agent",
            user_input=args.headless,
            tool_registry=tool_registry,
            # agent_type=args.agent_type,
            save_session_=args.save_session,
        )
        console.print(Markdown(r))
        return


if __name__ == "__main__":
    main()
