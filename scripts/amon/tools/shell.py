import subprocess

from config import DEFAULT_SHELL_TIMEOUT

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
    """Decode a subprocess stream that may be bytes when a timeout interrupts it."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream


def shell_readonly(
    command: list[str], cwd: str = ".", timeout: int = DEFAULT_SHELL_TIMEOUT
) -> str:
    """Run a whitelisted read-only command.

    Only accepts a command LIST: the whitelist is enforced on ``command[0]``, and
    a shell string would let anything past it (``"ls; rm -rf ."`` starts with
    ``"l"``, which is simply rejected).
    """
    if not command:
        raise ValueError("Empty command")

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
) -> str:
    """Execute a command and return its output.

    Args:
        command: argv list, or a shell string (pipes, redirects, ``&&``).
        cwd: working directory.
        timeout: seconds to wait. Raise it for long jobs (solvers, builds,
            test suites); on expiry the output captured so far is RETURNED
            rather than lost, so a partial run is still readable.
        shell: run through the shell. Implied by a string *command*; set it to
            join an argv list into one shell command line.

    Security: a shell string has no argv boundary, so anything interpolated into
    it is executed. Prefer a list unless shell features are actually needed.
    """
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
