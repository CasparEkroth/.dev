"""Interactive terminal UI for amon: footer, prompts, confirm, stream panels.

Implementation is split across ``terminal_ui``, ``terminal_footer``, and
``terminal_format``; this module re-exports the public surface so existing
``from scripts.amon.terminal import …`` / ``scripts.amon import terminal``
call sites stay stable.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import time
from uuid import UUID

try:
    import termios
except ImportError:  # pragma: no cover - POSIX only
    termios = None

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

import questionary
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from scripts.amon.memory import load_session, load_session_info
from scripts.amon.terminal_footer import (
    StatusFooter as StatusFooter,
    _session_allowed_tools as _session_allowed_tools,
    footer as footer,
    reset_context as reset_context,
    set_context_limit as set_context_limit,
    update_footer as update_footer,
)
from scripts.amon.terminal_format import (
    _format_args,
    _format_write,
    _render_spawn_agents_result as _render_spawn_agents_result,
)
from scripts.amon.terminal_ui import (
    _pause_live,
    _stderr_console,
    _ui_print,
    console as console,
    spinner_context as spinner_context,
)
from scripts.amon.tools.agent import Agent
from scripts.amon.tools.registry import READY_AGENTS
from scripts.amon.tools.todo import get_todos, render_todos

#: Matches one rendered checklist line, e.g. "◐ [in_progress] write tests"
#: (see scripts.amon.tools.todo.render_todos) — used to pull just the
#: checklist lines back out of a todo_write tool result string, which may
#: also contain validation notes ahead of the rendered list.
_TODO_LINE_RE = re.compile(r"^[○◐✓] \[(?:pending|in_progress|completed)\] .+$")


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
    choices = []
    for p, ts in sessions:
        info = load_session_info(p.name)
        label = f"{p.name[:8]}…  {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}"
        if info.get("agent"):
            label += f"  [{info['agent']}]"
        if info.get("preview"):
            label += f"  {info['preview']}"
        choices.append(questionary.Choice(title=label, value=p))
    choices.append(questionary.Choice(title="[cancel]", value=None))
    return questionary.select("Pick a session to resume:", choices=choices).ask()


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


def confirm_tool(name: str, args: dict) -> tuple[bool, str | None]:
    """Ask the user to approve one tool call.

    Returns ``(allowed, deny_reason)``. ``deny_reason`` is the free text the
    user optionally typed on a denial, fed back to the model so it can
    course-correct instead of retrying the same call blind.
    """
    if name in _session_allowed_tools:
        return True, None

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
        answer = input("Allow? [y/N/a=always allow this tool this session]: ")
        answer = answer.strip().lower()
        if answer == "a":
            _session_allowed_tools.add(name)
            return True, None
        if answer == "y":
            return True, None
        reason = input("Reason (optional, shown to the agent): ").strip()
        return False, (reason or None)


def stream_action(event: str, data: dict, *, console: Console | None = None) -> None:
    """Render one agent event. Pass console=_stderr_console to keep stdout clean."""
    out = console if console is not None else globals()["console"]

    def _print(*args, **kwargs) -> None:
        # Stdout path shares Live with the spinner; stderr does not.
        if out is globals()["console"]:
            _ui_print(*args, console=out, **kwargs)
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
            formatted = _format_write(data.get("args"))
            body = f"[bold]{data.get('name')}[/bold]\n{formatted}"
        else:
            formatted = _format_args(data.get("args"))
            body = f"[bold]{data.get('name')}[/bold]\n[dim]{formatted}[/dim]"
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
        if name == "spawn_agents":
            _print(_render_spawn_agents_result(content))
            return
        max_len = 600
        if len(content) > max_len:
            content = (
                content[:max_len]
                + "\n... (truncated, "
                + str(len(content))
                + " chars total)"
            )
        from rich.markup import escape

        _print(
            Panel(
                escape(content),
                title=f"[dim]← Result from {name}[/dim]",
                border_style="dim",
            )
        )
    elif event == "child_stderr":
        # A spawn_agents child's own stream_action_stderr output, forwarded
        # live instead of sitting buffered and discarded until the whole
        # batch finishes (or is dropped entirely unless JSON parsing fails).
        # Escape the WHOLE assembled body (including the literal "[" "]"
        # around the agent name) as one unit, then add real markup outside
        # that — the line is the child's own already-rendered panel output,
        # which can itself contain "[...]" (e.g. a todo status label), and
        # escaping only the variables while leaving literal brackets typed
        # around them unescaped does not stop Rich from parsing those.
        from rich.markup import escape

        agent = data.get("agent", "?")
        line = data.get("line", "")
        body = escape(f"  │ [{agent}] {line}")
        _print(f"[dim]{body}[/dim]")


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
    table.add_column("Agent", style="magenta")
    table.add_column("Preview", style="white")
    table.add_column("Last modified", style="dim")
    from rich.markup import escape

    for idx, (p, ts) in enumerate(sessions):
        info = load_session_info(p.name)
        table.add_row(
            str(idx),
            p.name,
            escape(info.get("agent") or "-"),
            escape(info.get("preview") or "-"),
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
        )
    console.print(table)


def pick_agents(agents: dict[str, Agent] = READY_AGENTS) -> str | None:
    if not agents:
        console.print("[dim]No agents found.[/dim]")
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
