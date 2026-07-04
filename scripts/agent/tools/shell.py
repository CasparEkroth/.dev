import subprocess

def run_shell(command: list[str], cwd:str=".")-> str:
    r = subprocess.run(
        args=command,
        cwd=cwd,
    )
    return r.stdout
