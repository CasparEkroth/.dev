from contextlib import contextmanager
from pathlib import Path
import pprint
import re
import sys
import time
from uuid import UUID

try:
    import termios
except ImportError:  # pragma: no cover - POSIX only
    termios = None

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from rich.spinner import Spinner

import questionary
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from scripts.amon.memory import load_session
from scripts.amon.tools.agent import Agent
from scripts.amon.tools.registry import READY_AGENTS
from scripts.amon.tools.todo import get_todos, render_todos
from config import BASE_CONTEXT_WINDOW

console = Console()
# Used only when stdout must stay machine-readable (e.g. --json).
_stderr_console = Console(file=sys.stderr)
_live: "Live | None" = None

#: Matches one rendered checklist line, e.g. "◐ [in_progress] write tests"
#: (see scripts.amon.tools.todo.render_todos) — used to pull just the
#: checklist lines back out of a todo_write tool result string, which may
#: also contain validation notes ahead of the rendered list.
_TODO_LINE_RE = re.compile(r"^[○◐✓] \[(?:pending|in_progress|completed)\] .+$")


class StatusFooter:
    def __init__(self, context_limit: int = BASE_CONTEXT_WINDOW):
        self.tokens = 0
        self.context_limit = context_limit
        self.context_current = 0
        self.todo_lines: list[str] = []

    def add_tokens(self, n: int) -> None:
        self.tokens += n

    def reset_footer(
        self, token: bool = False, context: bool = False, todos: bool = False
    ) -> None:
        if token:
            self.tokens = 0
        if context:
            self.context_current = 0
        if todos:
            self.todo_lines = []

    def set_context(self, c: int | str) -> None:
        self.context_current = c

    def set_todo_lines(self, lines: list[str]) -> None:
        self.todo_lines = lines

    def render_html(self) -> HTML:
        if isinstance(self.context_current, str):
            ctx = f"{self.context_current}/{self.context_limit:,}"
            pct = 0.0
        else:
            ctx = f"{self.context_current:,}/{self.context_limit:,}"
            pct = (
                (self.context_current / self.context_limit) * 100
                if self.context_limit
                else 0.0
            )
        text = f"Tokens: <b>{self.tokens:,}</b>   |   Context: <b>{ctx}</b> ({pct:.1f}%)"
        if self.todo_lines:
            text += "\n" + "\n".join(self.todo_lines)
        return HTML(text)


footer = StatusFooter()


def update_footer(tokens_added: int = 0, context: int | str = 0) -> None:
    if tokens_added:
        footer.add_tokens(tokens_added)
    if context:
        footer.set_context(context)


def reste_context() -> None:
    footer.reset_footer(context=True, todos=True)


def set_context_limit(limit: int) -> None:
    footer.context_limit = limit


def show_welcome(session_id: UUID) -> None:
    console.print(
        Panel(
            "[bold cyan]Agent[/bold cyan]  [dim]AI coding assistant[/dim]",
            subtitle="[dim]/exit · /agent · /new · /sessions[/dim]",
            border_style="cyan",
        )
    )
    existing_todos = get_todos(str(session_id))
    if existing_todos:
        footer.set_todo_lines(render_todos(existing_todos).splitlines())
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
def spinner_context(label: str = "Thinking…", *, stderr: bool = False):
    """Show a transient spinner while work runs.

    Interactive / pretty output must share the same Console as panels, otherwise
    Live (spinner) and stdout prints fight over the cursor and borders clip.

    Pass stderr=True only for machine-readable modes (--json) so stdout stays clean.
    """
    global _live
    target = _stderr_console if stderr else console
    with Live(
        Spinner("dots", text=f" {label}"),
        console=target,
        transient=True,
        refresh_per_second=10,
        # vertical_overflow keeps long panel prints from shredding the live line
        vertical_overflow="visible",
    ) as live:
        _live = live
        try:
            yield
        finally:
            _live = None


@contextmanager
def _pause_live():
    """Stop the spinner Live around multi-line UI so borders don't clip/race."""
    live = _live
    if live is not None:
        live.stop()
    try:
        yield
    finally:
        if live is not None and _live is live:
            # Only restart if spinner_context still owns this Live instance.
            live.start()


def _ui_print(*args, **kwargs) -> None:
    """Print UI chrome without fighting the active spinner."""
    with _pause_live():
        console.print(*args, **kwargs)


def _toolbar_text():
    return footer.render_html()


_toolbar_style = Style.from_dict(
    {"bottom-toolbar": "noreverse fg:ansiwhite bg:ansiblack"}
)


def make_prompt_session() -> PromptSession:
    return PromptSession(
        history=InMemoryHistory(),
        bottom_toolbar=_toolbar_text,
        refresh_interval=0.5,
        style=_toolbar_style,
    )


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


def _format_args(args) -> str:
    """Pretty-format tool args so panel borders wrap cleanly."""
    width = max(40, (console.width or 80) - 8)
    try:
        return pprint.pformat(args, width=width, compact=True, sort_dicts=False)
    except Exception:
        return str(args)


def _format_write(args: dict | list | None) -> str:
    """Format write_file args with red old / green new markup.

    write_file tool args look like:
      {"content": [{"path": "...", "old": "...", "new": "..."}, ...]}
    """
    from rich.markup import escape

    if isinstance(args, dict):
        items = args.get("content") or []
    elif isinstance(args, list):
        items = args
    else:
        items = []

    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = escape(str(item.get("path") or ""))
        old_text = escape(str(item.get("old") or "-"))
        new_text = escape(str(item.get("new") or ""))
        parts.append(
            f"[cyan]{path}[/cyan]\n"
            f"[bold red]- {old_text}[/bold red]\n"
            f"[bold green]+ {new_text}[/bold green]"
        )
    return "\n\n".join(parts) if parts else _format_args(args)


def _restore_echo() -> None:
    """Force local echo + canonical mode back on before a plain input(),
    and discard any stale bytes already queued on stdin.

    prompt_toolkit's PromptSession (the main "> " prompt) puts the tty in
    raw/no-echo mode while it owns input, and doesn't always restore it on
    an abnormal exit (e.g. Ctrl+C during the CPR hang) — that's the masked
    "password prompt" look. Worse, an unanswered cursor-position query
    (\x1b[6n) can leave the terminal's reply (\x1b[<row>;<col>R) sitting
    unread in the input queue; since it has no newline, it silently
    prepends itself to the next line you type, so a clean "y" arrives as
    e.g. "\x1b[24;5Ry" and never matches. TCIFLUSH drops that stale input.
    """
    if termios is None or not sys.stdin.isatty():
        return
    try:
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        attrs[3] |= termios.ECHO | termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
    except termios.error:
        pass


def confirm_tool(name: str, args: dict) -> bool:
    # Pause Live so the confirm panel owns the terminal cleanly.
    # Plain input() here, not questionary/prompt_toolkit: prompt_toolkit's
    # cursor-position (CPR) handshake can race with Live's just-stopped
    # render thread and leave the tty unable to register keystrokes.
    if name == "write_file":
        formatted = f"[bold yellow]{name}[/bold yellow]\n{_format_write(args)}"
    else:
        formatted = (
            f"[bold yellow]{name}[/bold yellow]\n[dim]{_format_args(args)}[/dim]"
        )
    with _pause_live():
        console.print(
            Panel(
                formatted,
                title="[yellow]⚠ Tool Request[/yellow]",
                border_style="yellow",
            )
        )
        _restore_echo()
        answer = input("Allow? [y/N]: ").strip().lower()
        return answer == "y"


def stream_action(event: str, data: dict, *, console: Console | None = None) -> None:
    """Render one agent event. Pass console=_stderr_console to keep stdout clean."""
    out = console if console is not None else globals()["console"]

    def _print(*args, **kwargs) -> None:
        # Stdout path shares Live with the spinner; stderr does not.
        if out is globals()["console"]:
            _ui_print(*args, **kwargs)
        else:
            out.print(*args, **kwargs)

    if event == "reasoning":
        _print(
            Panel(
                Markdown(data.get("content", "")),
                title="[bold green]Agent[/bold green]",
                border_style="green",
            )
        )
    elif event == "tool_call":
        if data.get("name") == "write_file":
            formated = _format_write(data.get("args"))
            body = f"[bold]{data.get('name')}[/bold]\n{formated}"
        else:
            formated = _format_args(data.get("args"))
            body = f"[bold]{data.get('name')}[/bold]\n[dim]{formated}[/dim]"
        _print(
            Panel(
                body,
                title="[cyan]→ Tool[/cyan]",
                border_style="cyan",
            )
        )
    elif event == "tool_result":
        content = str(data.get("content", ""))
        name = data.get("name", "tool")
        if name == "todo_write":
            # Keep the bottom-toolbar checklist in sync with every call, not
            # just what's visible in the scrolling panel below.
            footer.set_todo_lines(
                [line for line in content.splitlines() if _TODO_LINE_RE.match(line)]
            )
            # Escape first: rendered lines contain literal "[in_progress]" etc,
            # and Rich's console markup would otherwise parse "[...]" as style
            # tags and silently swallow the status label.
            from rich.markup import escape

            _print(
                Panel(
                    escape(content),
                    title="[magenta]☑ Checklist[/magenta]",
                    border_style="magenta",
                )
            )
            return
        max_len = 600
        if len(content) > max_len:
            content = (
                content[:max_len]
                + "\n... (truncated, "
                + str(len(content))
                + " chars total)"
            )
        _print(
            Panel(
                content,
                title=f"[dim]← Result from {name}[/dim]",
                border_style="dim",
            )
        )


def stream_action_stderr(event: str, data: dict) -> None:
    """Headless streamer: same panels, always on stderr."""
    stream_action(event, data, console=_stderr_console)


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


def print_headless_result(results: list[dict] | dict) -> None:
    """Pretty-print results returned by spawn_agents in --headless mode."""
    if isinstance(results, dict):
        # Backward-compat: {"agent:task": "text"} or single payload dict.
        if "agent" in results or "result" in results:
            items = [results]
        else:
            items = [
                {"agent": key, "task": "", "result": value, "ok": True}
                for key, value in results.items()
            ]
    else:
        items = results

    for item in items:
        agent = item.get("agent") or "agent"
        task = item.get("task") or ""
        title = f"[bold cyan]{agent}[/bold cyan]"
        if task:
            title = f"{title} [dim]— {task}[/dim]"

        if item.get("ok", True):
            body = item.get("result") or ""
            console.print(Panel(Markdown(str(body)), title=title, border_style="cyan"))
        else:
            err = item.get("error") or "Unknown error"
            console.print(Panel(f"[red]{err}[/red]", title=title, border_style="red"))

        meta_parts = []
        usage = item.get("usage") or {}
        if usage.get("total_tokens"):
            meta_parts.append(f"tokens={usage['total_tokens']}")
        if item.get("turns"):
            meta_parts.append(f"turns={item['turns']}")
        tools_used = item.get("tools_used") or []
        if tools_used:
            meta_parts.append(f"tools={', '.join(tools_used)}")
        if item.get("session_id"):
            meta_parts.append(f"session={item['session_id']}")
        if meta_parts:
            console.print(f"[dim]{' · '.join(meta_parts)}[/dim]")
