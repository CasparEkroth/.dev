from contextlib import contextmanager
from pathlib import Path
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner

import questionary
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

console = Console()
_live: "Live | None" = None


def show_welcome() -> None:
    console.print(
        Panel(
            "[bold cyan]Agent[/bold cyan]  [dim]AI coding assistant[/dim]",
            subtitle="[dim]/exit · /new · /sessions[/dim]",
            border_style="cyan",
            expand=False,
        )
    )


@contextmanager
def spinner_context(label: str = "Thinking…"):
    global _live
    with Live(
        Spinner("dots", text=f" {label}"),
        console=console,
        transient=True,
        refresh_per_second=10,
    ) as live:
        _live = live
        try:
            yield
        finally:
            _live = None


def make_prompt_session() -> PromptSession:
    return PromptSession(history=InMemoryHistory())


def pick_session(sessions: list[tuple[Path, float]]) -> Path | None:
    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return None
    choices = [
        questionary.Choice(
            title=f"{p.name[:8]}…  {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}",
            value=p,
        )
        for p, ts in sessions
    ]
    choices.append(questionary.Choice(title="[cancel]", value=None))
    return questionary.select("Pick a session to resume:", choices=choices).ask()


def confirm_tool(name: str, args: dict) -> bool:
    if _live is not None:
        _live.stop()
    try:
        console.print(
            Panel(
                f"[bold yellow]{name}[/bold yellow]\n[dim]{args}[/dim]",
                title="[yellow]⚠ Tool Request[/yellow]",
                border_style="yellow",
            )
        )
        return questionary.confirm("Allow?", default=False).ask()
    finally:
        if _live is not None:
            _live.start()


def print_response(text: str) -> None:
    console.print(Markdown(text))


def print_sessions(sessions: list[tuple[Path, float]]) -> None:
    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("Session ID", style="cyan")
    table.add_column("Last modified", style="dim")
    for idx, (p, ts) in enumerate(sessions):
        table.add_row(
            str(idx),
            p.name,
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
        )
    console.print(table)
