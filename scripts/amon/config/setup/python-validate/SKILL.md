---
name: python-validate
description: Use whenever Python code has been written or edited and needs to be checked before being considered "done" — this includes syntax errors, type errors, lint issues, unused imports, and whether existing tests still pass. Trigger this any time you finish writing/editing a .py file, before telling the user code works, or when the user asks to "check", "validate", "lint", or "make sure this works" for Python code.
---

# Python Validate

Runs a fast, deterministic multi-stage check on Python code: syntax → lint → types → tests.
Always run this via the script — do not hand-inspect the code and declare it correct, since
static tools catch things a read-through misses (unused imports, type mismatches, undefined names).

## Usage

The script path is listed under `resources:` at the end of this loaded skill content — use that
path directly. Do **not** guess or hardcode a path like `scripts/check.py`.

```
python <path-from-resources> <path_to_file_or_dir> [--no-tests]
```

- Pass a single `.py` file, or a directory (checked recursively).
- `--no-tests` skips pytest — use this for standalone scripts with no test suite.
- The `shell` tool takes a command list — do not include shell operators (`2>&1`, `|`) as list items.

The script exits non-zero if any stage fails, and prints a JSON summary to stdout with this shape:

```json
{
  "syntax_ok": true,
  "ruff": {"ok": false, "issues": [{"file": "...", "line": 12, "code": "F401", "message": "..."}]},
  "mypy": {"ok": true, "issues": []},
  "pytest": {"ok": true, "passed": 5, "failed": 0, "skipped": 1},
  "overall_ok": false
}
```

## Instructions

1. After writing or editing Python code, run `scripts/check.py` on the affected file(s) or the
   containing package — not the whole repo unless asked, to keep output focused.
2. Read the JSON summary. If `overall_ok` is `false`, fix the *first* stage that failed before
   re-running — syntax errors make lint/type/test results meaningless, so don't chase later-stage
   issues until earlier stages pass.
3. For `ruff` issues: fix them directly, don't suppress with `# noqa` unless the user asks or the
   rule is a clear false positive (explain why if you suppress).
4. For `mypy` issues: prefer fixing the actual type mismatch over adding `# type: ignore`.
4. For `pytest` failures: read the failing test's assertion output (the script includes it in
   `pytest.issues`) before guessing at a fix.
5. Re-run the script after each fix. Don't declare code "working" without an `overall_ok: true`
   result, or without explaining to the user which stage you couldn't verify (e.g. no test suite
   present).
6. If a required tool (ruff, mypy, pytest) isn't installed, the script reports that stage as
   `"skipped": true` rather than failing — mention this to the user rather than silently ignoring it.

## When NOT to use

- Trivial one-line snippets shown inline in chat with no file involved — just reason about them directly.
- Pure explanation/read requests ("what does this function do") — no validation needed.
