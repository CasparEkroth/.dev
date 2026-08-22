import subprocess

from config import DEFAULT_SHELL_TIMEOUT
from shared.path_guard import check_command_allowed, check_path_access

READONLY_COMMANDS = {
    "ls",
    "grep",
    "find",
    "wc",
    "tree",
    "pwd",
    "git",
}
READONLY_GIT_SUBCOMMANDS = {"status", "log", "diff", "show", "branch"}


def _as_text(stream: str | bytes | None) -> str:
    """Decode a subprocess stream, which may be bytes after a timeout."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream


def shell_readonly(
    command: list[str],
    cwd: str = ".",
    timeout: int = DEFAULT_SHELL_TIMEOUT,
    allow_paths: list[str] | None = None,
    deny_paths: list[str] | None = None,
    denied_commands: list[str] | None = None,
) -> str:
    """Run a whitelisted read-only command.

    Takes a list only: the whitelist is enforced on ``command[0]``, which a
    shell string would bypass. Agent path/command guards (when configured)
    layer on top of the whitelist — both must pass.

    Path checks only cover ``cwd``. A permitted command can still read paths
    outside ``allow_paths`` via absolute args; full containment needs OS
    sandboxing and is out of scope.
    """
    if not command:
        raise ValueError("Empty command")

    check_path_access(cwd, allow_paths=allow_paths, deny_paths=deny_paths)
    check_command_allowed(command, denied_commands=denied_commands)

    cmd = command[0]
    if cmd not in READONLY_COMMANDS:
        raise ValueError(
            f"'{cmd}' is not allowed for shell_readonly. Allowed: {sorted(READONLY_COMMANDS)}"
        )

    if cmd == "git":
        if len(command) < 2 or command[1] not in READONLY_GIT_SUBCOMMANDS:
            raise ValueError(
                f"git subcommand must be one of {sorted(READONLY_GIT_SUBCOMMANDS)}"
            )

    if cmd == "find" and "-exec" in command:
        raise ValueError("find -exec is not allowed in shell_readonly")

    r = subprocess.run(
        command, cwd=cwd, shell=False, capture_output=True, text=True, timeout=timeout
    )
    if r.returncode != 0:
        return f"Command failed (exit {r.returncode}):\n{r.stderr}"
    return r.stdout


def run_shell(
    command: list[str] | str,
    cwd: str = ".",
    timeout: int = DEFAULT_SHELL_TIMEOUT,
    shell: bool = False,
    allow_paths: list[str] | None = None,
    deny_paths: list[str] | None = None,
    denied_commands: list[str] | None = None,
) -> str:
    """Run *command* (argv list, or shell string for pipes and redirects).

    On timeout the output captured so far is returned instead of raising. A
    shell string has no argv boundary, so prefer a list.

    When agent guards are configured, ``cwd`` is checked against
    ``allow_paths`` / ``deny_paths`` and command-position names against
    ``denied_commands`` (including after ``&&`` / ``;`` / ``|`` in shell
    strings). This is a guardrail, not a sandbox: a permitted binary can still
    touch paths outside the allow tree via absolute paths or ``cd``.
    """
    check_path_access(cwd, allow_paths=allow_paths, deny_paths=deny_paths)
    check_command_allowed(command, denied_commands=denied_commands)

    shell = shell or isinstance(command, str)
    if shell and isinstance(command, list):
        command = " ".join(command)

    try:
        r = subprocess.run(
            args=command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
        )
    except subprocess.TimeoutExpired as exc:
        partial = f"{_as_text(exc.stdout)}{_as_text(exc.stderr)}"
        return f"Command timed out after {timeout}s (partial output):\n{partial}"

    if r.returncode != 0:
        return f"Command failed (exit {r.returncode}):\n{r.stdout}{r.stderr}"
    return r.stdout
