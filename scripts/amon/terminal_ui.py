"""Shared Rich console + live-spinner helpers for interactive terminal UI."""

from __future__ import annotations

from contextlib import contextmanager
import sys

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

console = Console()
# Used only when stdout must stay machine-readable (e.g. --json).
_stderr_console = Console(file=sys.stderr)
_live: "Live | None" = None


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


def _ui_print(*args, console: Console | None = None, **kwargs) -> None:
    """Print UI chrome without fighting the active spinner.

    `console` lets callers (e.g. terminal.stream_action) route output to a
    console they hold a reference to — this module's own `console` global
    stays live-spinner-aware but isn't the only valid target.
    """
    target = console if console is not None else globals()["console"]
    with _pause_live():
        target.print(*args, **kwargs)
