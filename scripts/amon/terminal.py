from contextlib import contextmanager
from pathlib import Path
import time
from uuid import UUID

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner

import questionary
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from scripts.amon.memory import load_session
from scripts.amon.tools.agent import READY_AGENTS, Agent

console = Console()
_live: "Live | None" = None


def show_welcome(session_id: UUID) -> None:
    console.print(
        Panel(
            "[bold cyan]Agent[/bold cyan]  [dim]AI coding assistant[/dim]",
            subtitle="[dim]/exit · /agent · /new · /sessions[/dim]",
            border_style="cyan",
            expand=False,
        )
    )
    history = load_session(session_id)
    if history:
        console.print(
            Panel(
                "[bold]Previous conversation[/bold]", border_style="dim", expand=False
            )
        )
        for msg in history:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "tool" or not content:
                continue
            if role == "user":
                console.print(
                    Panel(
                        Markdown(content),
                        title="[bold cyan]You[/bold cyan]",
                        border_style="cyan",
                    )
                )
            elif role == "assistant":
                console.print(
                    Panel(
                        Markdown(content),
                        title="[bold green]Agent[/bold green]",
                        border_style="green",
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


def stream_action(event: str, data: dict) -> None:
    if event == "reasoning":
        console.print(
            Panel(
                Markdown(data.get("content", "")),
                title="[bold green]Agent[/bold green]",
                border_style="green",
            )
        )
    elif event == "tool_call":
        console.print(
            Panel(
                f"[bold]{data.get('name')}[/bold]\n[dim]{data.get('args')}[/dim]",
                title="[cyan]→ Tool[/cyan]",
                border_style="cyan",
            )
        )
    elif event == "tool_result":
        content = str(data.get("content", ""))
        max_len = 600
        if len(content) > max_len:
            content = (
                content[:max_len]
                + "\n... (truncated, "
                + str(len(content))
                + " chars total)"
            )
        console.print(
            Panel(
                content,
                title=f"[dim]← Result from {data.get('name', 'tool')}[/dim]",
                border_style="dim",
            )
        )


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


def pick_agents(agents: dict[str, Agent] = READY_AGENTS) -> str | None:
    if not agents:
        console.print("[dim]No Agnets found.[/dim]")
        return None
    choices = [
        questionary.Choice(
            title=k,
            value=k,
        )
        for k, v in list(agents.items())
    ]
    choices.append(questionary.Choice(title="[cancel]", value=None))
    return questionary.select("Pick a agent to use:", choices=choices).ask()


def print_headless_result(results: dict[str, str]) -> None:
    """Pretty-print results returned by spawn_agents in --headless mode."""
    for key, value in results.items():
        console.print(Panel(Markdown(value), title=f"[bold cyan]{key}[/bold cyan]"))
