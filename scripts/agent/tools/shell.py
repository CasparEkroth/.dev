import subprocess


def run_shell(command: list[str], cwd: str = ".") -> str:
    r = subprocess.run(
        args=command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        return f"Command failed (exit {r.returncode}):\n{r.stderr}"
    return r.stdout
