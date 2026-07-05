from scripts.agent.agent_loop import run_agent
from scripts.agent.tools.registry import tool_registry
import argparse
from uuid import UUID

def main() -> None:
    parser = argparse.ArgumentParser(prog="agent")
    
    session= parser.add_mutually_exclusive_group()
    
    session.add_argument(
        "--resume",
        help="Resumes the last open session",
    )

    session.add_argument(
        "--resume-id",
        type=UUID,
        help="Resumes session on id",
    )
    
    session.add_argument(
        "--list",
        help="show list of sessions",
    )
    session.add_argument(
        "--delete-session",
        type=UUID,
        help="Delete session on id",
    )

    args = parser.parse_args()

    r = run_agent(
        system_prompt="you are a coding agent",
        user_input="what bash files are in this repo",
        tool_registry=tool_registry,
    )

    print(r)


if __name__ == "__main__":
    main()
