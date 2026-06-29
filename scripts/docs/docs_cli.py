from scripts.docs.search import search
import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="docs")

    parser.add_argument(
        "-q",
        "--query",
        required=True,
        help="Question/query to ask about the provided files",
    )

    args = parser.parse_args()

    print("Query:", args.query)
    resp = search(question=args.query)
    print(resp)

    


if __name__ == "__main__":
    main()
