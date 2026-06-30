from scripts.docs.search import search
import argparse
from pathlib import Path
from shared.file_handler import scan_folder

def main() -> None:
    parser = argparse.ArgumentParser(prog="docs")

    parser.add_argument(
        "-q",
        "--query",
        required=True,
        help="Question/query to ask about the provided files",
    )

    source = parser.add_mutually_exclusive_group(required=True)

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

    if args.file:
        files =[args.file]
    elif args.dir:
        files = scan_folder(
            cwd=args.dir,
            suffixes=set(args.suffix),
            excluded_dirs=set(args.exclude) if args.exclude else None,
        )
    
    print(args.query)
    print(files)
    #print("Query:", args.query)
    #resp = search(question=args.query)
    #print(resp)



if __name__ == "__main__":
    main()
