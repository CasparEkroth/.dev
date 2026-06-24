from scripts.vector.embeddings import add_vector, VectorItem
from scripts.vector.code.lang_adapters import (
    SUFFIX_TO_LANG,
    get_adapter,
)
from pathlib import Path
import hashlib


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def scan_folder(cwd: str) -> list[Path]:
    c = []
    skip = {".git", "__pycache__"}
    # add more (put in config)
    # add a centralized config
    for path in Path(cwd).rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if path.is_file():
            c.append(path)


def should_skip(file: str):
    pass


def llm_summarize_file(content: str):
    # Create file-level summary
    pass


def llm_summarize_symbol(symbols: str):
    # Create symbol-level embeddings
    pass


def split_into_logical_chunks(content: str):
    # Fallback chunks for large or unparsed files
    pass


def index_repo(repo_path):
    files = scan_folder(repo_path)

    for file in files:
        if should_skip(file):
            continue

        with open(file, "r") as f:
            code = f.read()

        language = SUFFIX_TO_LANG.get(file.suffix)

        if language is None:
            continue

        adapter = get_adapter(language)

        symbols = adapter.extract_symbols(code)
        file_summary = llm_summarize_file(code)

        add_vector(
            {
                "kind": "file",
                "path": file.path,
                "language": language,
                "embedding_text": f"""
            File: {file.path}
            Language: {language}
            Summary: {file_summary}
            """,
            }
        )
        add_vector(
            VectorItem(
                id=f"symbol:{file}:{symbol.name}:{symbol.start_line}:{symbol.end_line}",
                text=embedding_text,
                payload={
                    "kind": "symbol",
                    "path": str(file),
                    "language": language,
                    "name": symbol.name,
                    "symbol_type": symbol.kind,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "hash": stable_hash(symbol_code),
                },
            )
        )

        for symbol in symbols:
            symbol_code = code[symbol.start : symbol.end]

            summary = llm_summarize_symbol(symbol_code)

            embedding_text = f"""
            Path: {file.path}
            Kind: {symbol.kind}
            Name: {symbol.name}
            Signature: {symbol.signature}
            Summary: {summary}
            Code:
            {symbol_code}
            """

            add_vector(
                {
                    "kind": "symbol",
                    "path": file.path,
                    "name": symbol.name,
                    "symbol_type": symbol.kind,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "hash": hash(symbol_code),
                    "embedding_text": embedding_text,
                }
            )

        chunks = split_into_logical_chunks(code)

        for chunk in chunks:
            add_vector(
                {
                    "kind": "chunk",
                    "path": file.path,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "embedding_text": f"""
                Path: {file.path}
                Lines: {chunk.start_line}-{chunk.end_line}
                Code:
                {chunk.text}
                """,
                }
            )
