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


def read_file(path: str, start_line: int = None, end_line: int = None) -> dict:
    abspath = os.path.abspath(path)
    with open(abspath, "r") as f:
        content = f.read()

    if content is None:
        return {
            "ok": False,
        }
    lines = content.splitlines()

    return {
        "ok": True,
        "content": lines[
            start_line if start_line else 0 : end_line if end_line else len(lines)
        ],
    }


def write_file(content: list[dict]) -> str:
    """Apply a batch of edits, creating files that do not exist yet.

    Each section is ``{"path": ..., "old": ..., "new": ...}``:

    * missing file + empty ``old`` + non-empty ``new`` -> the file (and any
      missing parent directories) is CREATED with ``new`` as its content;
    * existing file + empty ``old`` -> ``new`` is appended;
    * existing file + non-empty ``old`` -> the first occurrence is replaced.

    Returns one status line per section, so a partial batch still reports which
    sections applied.
    """
    results = []
    for section in content:
        raw_path = section.get("path") or ""
        old = section.get("old", "")
        new = section.get("new", "")
        if not raw_path:
            results.append("<no path>: missing 'path', no changes made")
            continue
        path = Path(raw_path)
        # handel old is eampty####
        if not path.is_file():
            # No file yet: an empty `old` with content to write means "create it".
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
