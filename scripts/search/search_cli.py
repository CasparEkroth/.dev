from scripts.search.search import search
from scripts.search.prompts import (
    WEB_SEARCH_PROMPT,
    ROUTER_PROMPT,
    NO_SEARCH_PROMPT,
)
import json
import argparse
from pathlib import Path
from shared.file_handler import scan_folder, read_files
from shared.llm_client import call_llm
from rich.status import Status
from rich.console import Console
from rich.markdown import Markdown


def main() -> None:
    parser = argparse.ArgumentParser(prog="search")

    parser.add_argument(
        "query",
        help="Question/query to ask about the provided files",
    )

    source = parser.add_mutually_exclusive_group()

    source.add_argument(
        "-f",
        "--file",
        type=Path,
        dest="file",
        help="Single file to include as context",
    )

    source.add_argument(
        "-d",
        "--dir",
        type=Path,
        dest="dir",
        help="Directory to scan for files",
    )

    parser.add_argument(
        "-s",
        "--suffix",
        nargs="*",
        default=[".py", ".md", ".txt"],
        help="File suffixes to include when using --dir",
    )

    parser.add_argument(
        "-e",
        "--exclude",
        nargs="*",
        default=[".venv", "node_modules", ".git", "__pycache__"],
        help="Directory names to skip",
    )
    args = parser.parse_args()
    files = None
    if args.file:
        files = [args.file]
    elif args.dir:
        files = scan_folder(
            cwd=args.dir,
            suffixes=set(args.suffix),
            excluded_dirs=set(args.exclude) if args.exclude else None,
        )

    if files:
        file_content = read_files(files)
    else:
        file_content = "None"

    routing_prompt = ROUTER_PROMPT.format(
        user_input=args.query,
        files=file_content,
    )

    with Status("[bold green]Thinking...", spinner="dots"):
        routing_resp = json.loads(call_llm(routing_prompt))
    requires_search = routing_resp.get("requires_search")

    if requires_search:
        with Status("[bold green]Searching the web...", spinner="dots"):
            resp_search = search(question=routing_resp.get("search_query"))
        web_prompt = WEB_SEARCH_PROMPT.format(
            user_input=args.query,
            files=file_content,
            search_context=resp_search,
        )
        with Status("[bold green]Generating answer...", spinner="dots"):
            response = call_llm(prompt=web_prompt)
    else:
        no_web_prompt = NO_SEARCH_PROMPT.format(
            user_input=args.query,
            files=file_content,
        )
        with Status("[bold green]Generating answer...", spinner="dots"):
            response = call_llm(no_web_prompt)

    console = Console()
    console.print(Markdown(response))


if __name__ == "__main__":
    main()
