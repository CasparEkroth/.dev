"""Tests for the interactive REPL loop in amon_cli.py."""

import argparse
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from scripts.amon import terminal
from scripts.amon.agent_loop import AgentResult
from scripts.amon.amon_cli import _run_interactive


def _fake_agent():
    return SimpleNamespace(
        name="dev",
        system_prompt="sys",
        tools=[],
        allowed_tools=[],
        allow_paths=[],
        deny_paths=[],
        denied_commands=[],
        allowed_skills=[],
        hooks={},
        max_turns=10,
        force_first_tool=False,
        max_runtime_s=None,
        model=None,
        system_prompt_template=None,
    )


class _OneShotPromptSession:
    """Returns *user_input* once, then raises EOFError to end the REPL loop."""

    def __init__(self, user_input: str):
        self._input = user_input

    def prompt(self, *_args, **_kwargs):
        if self._input is None:
            raise EOFError
        value, self._input = self._input, None
        return value


def _ok_result(**overrides):
    defaults = dict(ok=True, result="done", session_id=str(uuid4()))
    defaults.update(overrides)
    return AgentResult(**defaults)


def _run_repl(user_input: str, result: AgentResult):
    args = argparse.Namespace(agent="dev")
    with (
        patch("scripts.amon.amon_cli.READY_AGENTS", {"dev": _fake_agent()}),
        patch("scripts.amon.amon_cli.run_agent", return_value=result),
        patch(
            "scripts.amon.amon_cli.terminal.make_prompt_session",
            return_value=_OneShotPromptSession(user_input),
        ),
        patch("scripts.amon.amon_cli.terminal.show_welcome"),
        patch("scripts.amon.amon_cli._resolve_session_id", return_value=uuid4()),
    ):
        _run_interactive(args)


class TestFooterResetsOnCompletion:
    def setup_method(self):
        terminal.footer.todo_lines = ["◐ [in_progress] step one"]

    def teardown_method(self):
        terminal.footer.reset_footer(todos=True)

    def test_successful_turn_clears_the_checklist(self):
        _run_repl("do the thing", _ok_result())
        assert terminal.footer.todo_lines == []

    def test_failed_turn_keeps_the_checklist(self):
        failed = _ok_result(ok=False, result="partial", error="Max turns reached")
        _run_repl("do the thing", failed)
        assert terminal.footer.todo_lines == ["◐ [in_progress] step one"]
