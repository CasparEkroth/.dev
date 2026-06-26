from scripts.vector.embeddings import add_vector, VectorItem
from scripts.vector.code.lang_adapters import (
    SUFFIX_TO_LANG,
    get_adapter,
)
from scripts.vector.code.adapter import Symbol
from scripts.vector.prompts import (
    SYMBOL_SUMMARY_PROMPT,
    FILE_SUMMARY_PROMPT
)
from shared.llm_client import call_llm
from config import (
    EXCLUDED_DIRS, 
    IGNORED_FILES
)
from pathlib import Path
import hashlib


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def scan_folder(cwd: str) -> list[Path]:
    c = []
    for path in Path(cwd).rglob("*"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.is_file():
            c.append(path)
    return c


def should_skip(file: str) -> bool:
    return (file in IGNORED_FILES)


def llm_summarize_file(content: str, language: str, file: Path):
    file_prompt = FILE_SUMMARY_PROMPT.format(
        path=str(file),
        language=language,
        content=content,
    )
    return call_llm(file_prompt)


def llm_summarize_symbol(symbol: Symbol, symbol_code: str, language: str, file: Path):
    symbol_prompt = SYMBOL_SUMMARY_PROMPT.format(
        path=str(file),
        language=language,
        kind=symbol.kind,
        name=symbol.name,
        signature=symbol.signature or "unknown",
        code=symbol_code,
    )
    return call_llm(symbol_prompt)


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

        file_summary = llm_summarize_file(
            content=code,
            language=language,
            file=file,
        )

        add_vector(
            {
                "kind": "file",
                "path": str(file),
                "language": language,
                "embedding_text": f"""
            File: {str(file)}
            Language: {language}
            Summary: {file_summary}
            """,
            }
        )

        adapter = get_adapter(language)
        symbols = adapter.extract_symbols(code)
        
        for symbol in symbols:
            symbol_code = code[symbol.start : symbol.end]

            summary = llm_summarize_symbol(
                symbol=symbol, 
                symbol_code=symbol_code, 
                language=language, 
                file=file
            )

            embedding_text = f"""
            Path: {str(file)}
            Kind: {symbol.kind}
            Name: {symbol.name}
            Signature: {symbol.signature}
            Summary: {summary}
            Code:
            {symbol_code}
            """

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

        chunks = split_into_logical_chunks(code)

        for chunk in chunks:# not done
            embedding_text = f"""
            Path: {str(file)}
            Kind: {symbol.kind}
            Name: {symbol.name}
            Signature: {symbol.signature}
            Summary: {summary}
            Code:
            {symbol_code}
            """
            add_vector(
                VectorItem(
                    id=f"symbol:{file}:{symbol.name}:{symbol.start_line}:{symbol.end_line}",
                    text=embedding_text,
                    payload={
                        "kind": "chunk",
                        "path": str(file),
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "hash": stable_hash(symbol_code),
                    }
                )
            )
