from scripts.agent.agent_loop import run_agent
from scripts.agent.tools.registry import tool_registry
import argparse
from uuid import UUID
from rich.console import Console
from rich.markdown import Markdown


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent")

    command = parser.add_mutually_exclusive_group()

    command.add_argument("--resume", help="Resumes the last open session")
    command.add_argument("--resume-id", type=UUID, help="Resumes session on id")
    command.add_argument("--list-sessions", help="show list of sessions")
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
        "--save-session", action="store_true", help="Save the session after completion"
    )

    args = parser.parse_args()
    console = Console()
    if args.headless:
        r = run_agent(
            system_prompt="you are a coding agent",
            user_input=args.headless,
            tool_registry=tool_registry,
            # agent_type=args.agent_type,
            # save_session=args.save_session,
        )
        console.print(Markdown(r))


if __name__ == "__main__":
    main()
