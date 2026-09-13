"""Bottom-toolbar status: tokens, context window, and live checklist lines."""

from __future__ import annotations

from prompt_toolkit.formatted_text import HTML

from config import BASE_CONTEXT_WINDOW

#: Tool names approved for the rest of the current REPL session via the
#: confirm prompt's "always" answer. Cleared on /new, same as the footer.
_session_allowed_tools: set[str] = set()


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
        header = (
            f"Tokens: <b>{self.tokens:,}</b>   |   Context: <b>{ctx}</b> ({pct:.1f}%)"
        )
        if not self.todo_lines:
            return HTML(header)
        # todo_lines is free-form text a todo_write call wrote — it can
        # contain "<" / "&" (e.g. "fix List<int> handling"), which HTML()
        # would otherwise try to parse as markup and raise ExpatError,
        # crashing the bottom-toolbar render. header's own <b> tags are real
        # markup and must NOT go through this escaping, so only the
        # placeholder gets it via .format().
        return HTML(header + "\n{}").format("\n".join(self.todo_lines))


footer = StatusFooter()


def update_footer(tokens_added: int = 0, context: int | str | None = None) -> None:
    if tokens_added:
        footer.add_tokens(tokens_added)
    if context is not None:
        footer.set_context(context)


def reset_context() -> None:
    footer.reset_footer(context=True, todos=True)
    _session_allowed_tools.clear()


def set_context_limit(limit: int) -> None:
    footer.context_limit = limit
