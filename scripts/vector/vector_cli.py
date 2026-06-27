#!/usr/bin/env python3

from pathlib import Path
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="vector-index")
    subparsers = parser.add_subparsers(dest="command", required=True)

    repo_parser = subparsers.add_parser(
        "repo",
        help="Index a code repository",
        description="Create vector embeddings from source files in a repository."
    )
    repo_parser.add_argument("path", type=Path)
    repo_parser.add_argument("--out", type=Path, default=Path("vectors.json"))

    pdf_parser = subparsers.add_parser(
        "pdf",
        help="Index a PDF document",
        description="Create vector embeddings from pages or chunks in a PDF file."
    )
    pdf_parser.add_argument("path", type=Path)
    pdf_parser.add_argument("--out", type=Path, default=Path("vectors.json"))

    args = parser.parse_args()

    if args.command == "repo":
        if not args.path.is_dir():
            parser.error(f"Expected repo directory: {args.path}")

        from scripts.vector.code.index_code import index_repo
        from scripts.vector.embeddings import save_vectors

        print(f"Indexing repo: {args.path}")
        index_repo(args.path)

        print(f"Saving vectors to: {args.out}")
        save_vectors(args.out)

        print("Done")

    elif args.command == "pdf": #TODO add a index_pdf
        if not args.path.is_file() or args.path.suffix.lower() != ".pdf":
            parser.error(f"Expected PDF file: {args.path}")

        from scripts.vector.embeddings import save_vectors
        # from scripts.vector.pdf.index_pdf import index_pdf

        print(f"Indexing PDF: {args.path}")
        print("PDF indexing is not implemented yet")
        
        # index_pdf(args.path)
        # save_vectors(args.out)



if __name__ == "__main__":
    main()