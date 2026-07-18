import subprocess

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


def shell_readonly(command: list[str], cwd: str = ".") -> str:
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
        command, cwd=cwd, shell=False, capture_output=True, text=True, timeout=10
    )
    if r.returncode != 0:
        return f"Command failed (exit {r.returncode}):\n{r.stderr}"
    return r.stdout


def run_shell(command: list[str], cwd: str = ".") -> str:
    r = subprocess.run(
        args=command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        return f"Command failed (exit {r.returncode}):\n{r.stdout}{r.stderr}"
    return r.stdout
