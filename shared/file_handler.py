from pathlib import Path
import os

from shared.path_guard import check_path_access


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


def read_files(paths: list[Path]) -> list[dict]:
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


def read_file(
    path: str,
    start_line: int = None,
    end_line: int = None,
    allow_paths: list[str] | None = None,
    deny_paths: list[str] | None = None,
) -> dict:
    check_path_access(path, allow_paths=allow_paths, deny_paths=deny_paths)
    abspath = os.path.abspath(path)
    with open(abspath, "r") as f:
        content = f.read()

    if content is None:
        return {
            "ok": False,
        }
    lines = content.splitlines()
    total_lines = len(lines)

    # Tool schema is 1-based inclusive; convert to 0-based slice indices.
    start = max(start_line - 1, 0) if start_line else 0
    end = end_line if end_line else total_lines
    return {
        "ok": True,
        "path": abspath,
        # 1-based range actually returned (end clamped to file length).
        "start_line": start + 1,
        "end_line": min(end, total_lines),
        "total_lines": total_lines,
        "content": lines[start:end],
    }


def write_file(
    content: list[dict],
    allow_paths: list[str] | None = None,
    deny_paths: list[str] | None = None,
) -> str:
    """Apply a batch of ``{"path", "old", "new", "overwrite"?}`` edits, one status line each.

    ``overwrite: true`` replaces the whole file with ``new`` (creating it, and
    any missing parent directories, if it doesn't exist yet) — ``old`` is
    ignored. Otherwise: empty ``old`` appends, or creates the file when it
    does not exist yet; otherwise the first occurrence of ``old`` is replaced.
    """
    # Pre-check every path so a mid-batch deny cannot leave partial writes.
    if allow_paths or deny_paths:
        for section in content:
            raw = section.get("path") or ""
            if raw:
                check_path_access(raw, allow_paths=allow_paths, deny_paths=deny_paths)

    results = []
    for section in content:
        raw_path = section.get("path") or ""
        old = section.get("old", "")
        new = section.get("new", "")
        overwrite = bool(section.get("overwrite", False))
        if not raw_path:
            results.append("<no path>: missing 'path', no changes made")
            continue
        path = Path(raw_path)

        if overwrite:
            existed = path.is_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new)
            results.append(f"{path}: {'overwritten' if existed else 'created file'}")
            continue

        # handel old is eampty####
        if not path.is_file():
            if old == "" and new != "":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(new)
                results.append(f"{path}: created file")
                continue
            results.append(f"{path}: file not found")
            continue

        current_file = path.read_text()

        if old == "":
            updated_file = current_file + new
            path.write_text(updated_file)
            results.append(f"{path}: appended content")
            continue

        if old not in current_file:
            results.append(f"{path}: search text not found, no changes made")
            continue

        updated_file = current_file.replace(old, new, 1)
        path.write_text(updated_file)
        results.append(f"{path}: updated successfully")

    return "\n".join(results)
