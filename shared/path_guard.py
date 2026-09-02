"""Server-side path/command allow-deny checks for agent tools.

These guards are agent-config only — never exposed in tool schemas — so the
model cannot pass them as arguments. They are a guardrail against accidental
damage, not an OS-level sandbox: ``shell`` can still touch paths outside
``allow_paths`` via absolute paths or ``cd`` inside a permitted command.
``read_file`` / ``write_file`` enforcement is a hard boundary because those
tools never shell out.
"""

from __future__ import annotations

import re
import shlex
from fnmatch import fnmatch
from pathlib import Path

# Tokens that start a new command position in a shell string.
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "|&", "&"})
# shlex keeps ``;``/``|``/``&`` glued to adjacent words (``true;``, ``echo|curl``).
# Split those out after shlex so command-position scan sees real separators.
# Longer forms first so ``&&`` is not read as two ``&``.
_GLUED_SEP_RE = re.compile(r"(&&|\|\||\|&|;|\||&)")
# Redirect operators — skip them (and their targets stay non-commands).
_REDIRECT_PREFIXES = (">", ">>", "<", "<<", "2>", "2>>", "&>", ">&")


def resolve_path(path: str | Path) -> Path:
    """Expand ``~`` and resolve symlinks / ``..`` to an absolute path."""
    return Path(path).expanduser().resolve()


def _expand_pattern(pattern: str) -> str:
    """Expand ``~`` in a glob pattern without resolving globs away."""
    return str(Path(pattern).expanduser())


def path_matches(path: str | Path, patterns: list[str] | None) -> str | None:
    """Return the first glob pattern that matches *path*, else ``None``.

    *path* is resolved before matching. Patterns are compared with
    :func:`fnmatch.fnmatch` against the resolved absolute path string so
    ``**`` and absolute prefixes both work. A pattern ending in ``/**`` also
    matches the directory prefix itself (so ``/work/**`` allows cwd ``/work``).
    """
    if not patterns:
        return None
    resolved = str(resolve_path(path))
    for raw in patterns:
        pat = _expand_pattern(raw)
        if fnmatch(resolved, pat):
            return raw
        # ``/work/**`` should include the directory ``/work`` itself.
        if pat.endswith("/**") and resolved == pat[: -len("/**")]:
            return raw
    return None


def check_path_access(
    path: str | Path,
    allow_paths: list[str] | None = None,
    deny_paths: list[str] | None = None,
) -> None:
    """Raise ``PermissionError`` when *path* is blocked by agent path rules.

    A path is permitted iff it is not matched by any ``deny_paths`` pattern,
    AND (``allow_paths`` is empty/None OR matched by at least one allow
    pattern). Deny always wins. Empty allow = unrestricted (not deny-all).
    """
    if not allow_paths and not deny_paths:
        return

    resolved = resolve_path(path)
    denied_by = path_matches(resolved, deny_paths)
    if denied_by is not None:
        raise PermissionError(
            f"Path '{path}' (resolved: {resolved}) blocked by deny_paths "
            f"pattern '{denied_by}'"
        )

    if allow_paths:
        if path_matches(resolved, allow_paths) is None:
            raise PermissionError(
                f"Path '{path}' (resolved: {resolved}) is outside allow_paths "
                f"{list(allow_paths)}"
            )


def _is_env_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("="):
        return False
    name = token.split("=", 1)[0]
    return bool(name) and name[0].isalpha() and name.replace("_", "").isalnum()


def _is_redirect(token: str) -> bool:
    return token.startswith(_REDIRECT_PREFIXES) or token in {
        ">",
        ">>",
        "<",
        "<<",
        "2>",
        "2>>",
        "&>",
        ">&",
    }


def _unglue_shell_tokens(tokens: list[str]) -> list[str]:
    """Split shell control operators that shlex left attached to words.

    ``shlex.split("true; sudo")`` yields ``["true;", "sudo"]``; we need
    ``["true", ";", "sudo"]`` so ``;`` is recognized as a separator.
    """
    out: list[str] = []
    for tok in tokens:
        if tok in _SHELL_SEPARATORS:
            out.append(tok)
            continue
        parts = _GLUED_SEP_RE.split(tok)
        for part in parts:
            if part:
                out.append(part)
    return out


def command_names(command: list[str] | str) -> list[str]:
    """Return executable names that occupy command position(s).

    * argv list → basename of ``command[0]`` only.
    * shell string → basename of every token in command position after
      ``shlex``-splitting, including after ``&&`` / ``||`` / ``;`` / ``|`` /
      ``&``. Env assignments and redirects are skipped. This is still not a
      full shell parser (e.g. ``$(...)`` / backticks are not expanded).
    """
    if isinstance(command, list):
        if not command:
            return []
        return [Path(command[0]).name]

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    tokens = _unglue_shell_tokens(tokens)

    names: list[str] = []
    # 0 = expect command, 1 = skip one redirect-target token, 2 = in args
    state = 0
    for tok in tokens:
        if tok in _SHELL_SEPARATORS:
            state = 0
            continue
        if state == 2:
            continue
        if state == 1:
            state = 0
            continue
        if _is_env_assignment(tok):
            continue
        if _is_redirect(tok):
            # ``> file`` (two tokens) vs ``>file`` (one token via shlex).
            if tok in {">", ">>", "<", "<<", "2>", "2>>", "&>", ">&"}:
                state = 1
            continue
        names.append(Path(tok).name)
        state = 2
    return names


def check_command_allowed(
    command: list[str] | str,
    denied_commands: list[str] | None = None,
) -> None:
    """Raise ``PermissionError`` if any command-position name is denied."""
    if not denied_commands:
        return
    denied = set(denied_commands)
    for name in command_names(command):
        if name in denied:
            raise PermissionError(
                f"Command '{name}' is blocked by denied_commands {list(denied_commands)}"
            )


def check_no_traversal_in_args(
    command: list[str] | str,
    allow_paths: list[str] | None = None,
) -> None:
    """Reject any argument with a ``..`` path segment when ``allow_paths`` is set.

    No-op when ``allow_paths`` is empty/None. Absolute paths are not rejected.
    """
    if not allow_paths:
        return
    if isinstance(command, list):
        tokens = command
    else:
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            tokens = command.split()
    for tok in tokens:
        if ".." in Path(tok).parts:
            raise PermissionError(
                f"Argument '{tok}' contains '..' — blocked because allow_paths is set"
            )
