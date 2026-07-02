from pathlib import Path
import os

def scan_folder(
    cwd: str | Path,
    excluded_dirs: set[str] | None = None,
    suffixes: set[str] | None = None,
) -> list[Path]:

    excluded_dirs = excluded_dirs or set()
    if suffixes is not None:
        suffixes = {suffix.lstrip(".") for suffix in suffixes}
    files = []

    for path in Path(cwd).rglob("*"):
        if any(part in excluded_dirs for part in path.parts):
            continue
        if not path.is_file():
            continue        
        if suffixes is not None and path.suffix != "":
            if path.suffix.lstrip(".") not in suffixes:
                continue
        
        files.append(path)

    return files


def read_files(paths: list[Path]) -> dict:
    collection = []
    for path in paths:
        if not path.is_file():
            continue
        with open(path, "r") as f:
            collection.append(
                {
                    "file_name": path.name,
                    "path": str(path),
                    "content": f.read(),
                }
            )
    return collection