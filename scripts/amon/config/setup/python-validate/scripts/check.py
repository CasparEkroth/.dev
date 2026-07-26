#!/usr/bin/env python3
"""
Multi-stage Python validator: syntax -> ruff -> mypy -> pytest.

Usage:
    python check.py <path_to_file_or_dir> [--no-tests]

Prints a JSON summary to stdout and exits non-zero if overall_ok is False.
Each stage is skipped gracefully (not failed) if its tool isn't installed.
"""

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path


def find_py_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix == ".py" else []
    return sorted(path.rglob("*.py"))


def check_syntax(files: list[Path]) -> tuple[bool, list[dict]]:
    issues = []
    for f in files:
        try:
            ast.parse(f.read_text(), filename=str(f))
        except SyntaxError as e:
            issues.append(
                {
                    "file": str(f),
                    "line": e.lineno,
                    "message": str(e.msg),
                }
            )
    return (len(issues) == 0, issues)


def run_ruff(target: str) -> dict:
    if shutil.which("ruff") is None:
        return {"ok": True, "skipped": True, "issues": []}
    result = subprocess.run(
        ["ruff", "check", target, "--output-format=json"],
        capture_output=True,
        text=True,
    )
    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        raw = []
    issues = [
        {
            "file": item.get("filename"),
            "line": item.get("location", {}).get("row"),
            "code": item.get("code"),
            "message": item.get("message"),
        }
        for item in raw
    ]
    return {"ok": len(issues) == 0, "skipped": False, "issues": issues}


def run_mypy(target: str) -> dict:
    if shutil.which("mypy") is None:
        return {"ok": True, "skipped": True, "issues": []}
    result = subprocess.run(
        ["mypy", target, "--no-error-summary", "--show-error-codes"],
        capture_output=True,
        text=True,
    )
    issues = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) == 4 and "error" in parts[2]:
            issues.append(
                {
                    "file": parts[0],
                    "line": parts[1].strip(),
                    "message": parts[3].strip(),
                }
            )
    return {"ok": len(issues) == 0, "skipped": False, "issues": issues}


def run_pytest(target: str) -> dict:
    if shutil.which("pytest") is None:
        return {
            "ok": True,
            "skipped": True,
            "passed": 0,
            "failed": 0,
            "skipped_tests": 0,
            "issues": [],
        }
    result = subprocess.run(
        ["pytest", target, "-q", "--no-header"],
        capture_output=True,
        text=True,
    )
    tail = result.stdout.strip().splitlines()[-15:]
    passed = failed = skipped = 0
    for line in tail:
        if " passed" in line:
            for tok in line.replace(",", "").split():
                if tok.isdigit():
                    pass
            import re

            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", line)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+) skipped", line)
            if m:
                skipped = int(m.group(1))
    return {
        "ok": result.returncode == 0,
        "skipped": False,
        "passed": passed,
        "failed": failed,
        "skipped_tests": skipped,
        "issues": tail if result.returncode != 0 else [],
    }


def main():
    args = sys.argv[1:]
    run_tests = "--no-tests" not in args
    args = [a for a in args if a != "--no-tests"]

    if not args:
        print(json.dumps({"error": "usage: check.py <path> [--no-tests]"}))
        sys.exit(2)

    path = Path(args[0])
    if not path.exists():
        print(json.dumps({"error": f"path not found: {path}"}))
        sys.exit(2)

    files = find_py_files(path)
    target = str(path)

    syntax_ok, syntax_issues = check_syntax(files)
    result = {
        "syntax_ok": syntax_ok,
        "syntax_issues": syntax_issues,
        "ruff": None,
        "mypy": None,
        "pytest": None,
    }

    # Don't bother running further stages if syntax is broken
    if syntax_ok:
        result["ruff"] = run_ruff(target)
        result["mypy"] = run_mypy(target)
        if run_tests:
            result["pytest"] = run_pytest(target)

    overall_ok = (
        syntax_ok
        and (result["ruff"] is None or result["ruff"]["ok"])
        and (result["mypy"] is None or result["mypy"]["ok"])
        and (result["pytest"] is None or result["pytest"]["ok"])
    )
    result["overall_ok"] = overall_ok

    print(json.dumps(result, indent=2))
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
