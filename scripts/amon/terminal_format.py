"""Formatting helpers for tool args and spawn_agents result panels."""

from __future__ import annotations

import json
import pprint

from rich.panel import Panel
from rich.table import Table

from scripts.amon.terminal_ui import console


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


def _render_spawn_agents_result(content: str):
    """A small table instead of a wall of raw JSON, when it parses cleanly.

    ``content`` may already be truncated (see truncate_tool_output) — a cut
    mid-JSON is expected sometimes, not a bug, so fall back to the plain
    panel rather than raising.
    """
    fallback = Panel(
        content[:600] + ("..." if len(content) > 600 else ""),
        title="[dim]← Result from spawn_agents[/dim]",
        border_style="dim",
    )
    try:
        results = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return fallback
    if not isinstance(results, list):
        return fallback

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("Agent")
    table.add_column("OK")
    table.add_column("Tokens", justify="right")
    table.add_column("Turns", justify="right")
    table.add_column("Session")
    for r in results:
        if not isinstance(r, dict):
            continue
        ok_text = "[green]✓[/green]" if r.get("ok") else "[red]✗[/red]"
        tokens = (r.get("usage") or {}).get("total_tokens", 0)
        session = str(r.get("session_id") or "-")[:8]
        table.add_row(
            str(r.get("agent", "?")),
            ok_text,
            str(tokens),
            str(r.get("turns", "-")),
            session,
        )
    return Panel(
        table, title="[cyan]☰ spawn_agents results[/cyan]", border_style="cyan"
    )
