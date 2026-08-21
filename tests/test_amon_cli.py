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
        max_tool_output_chars=None,
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


def _run_repl(user_input: str, result: AgentResult, agent=None):
    args = argparse.Namespace(agent="dev")
    with (
        patch("scripts.amon.amon_cli.READY_AGENTS", {"dev": agent or _fake_agent()}),
        patch("scripts.amon.amon_cli.run_agent", return_value=result) as run_agent,
        patch(
            "scripts.amon.amon_cli.terminal.make_prompt_session",
            return_value=_OneShotPromptSession(user_input),
        ),
        patch("scripts.amon.amon_cli.terminal.show_welcome"),
        patch("scripts.amon.amon_cli._resolve_session_id", return_value=uuid4()),
    ):
        _run_interactive(args)
    return run_agent


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


class TestMaxToolOutputCharsParity:
    """Regression: interactive mode silently ignored an agent's
    max_tool_output_chars while headless/run_task honored it."""

    def test_agent_value_is_forwarded_to_run_agent(self):
        agent = _fake_agent()
        agent.max_tool_output_chars = 500
        run_agent_mock = _run_repl("do the thing", _ok_result(), agent=agent)
        assert run_agent_mock.call_args.kwargs["max_tool_output_chars"] == 500

    def test_none_is_forwarded_as_none(self):
        run_agent_mock = _run_repl("do the thing", _ok_result())
        assert run_agent_mock.call_args.kwargs["max_tool_output_chars"] is None


class TestCompactCommand:
    """/compact must share the same safety net as auto-compact, not the bare
    (unfinished-tool-unaware, no-fallback) compact_conversation call."""

    def _run_compact(self, conversation, compact_history_return):
        args = argparse.Namespace(agent="dev")
        with (
            patch("scripts.amon.amon_cli.READY_AGENTS", {"dev": _fake_agent()}),
            patch(
                "scripts.amon.amon_cli.terminal.make_prompt_session",
                return_value=_OneShotPromptSession("/compact"),
            ),
            patch("scripts.amon.amon_cli.terminal.show_welcome"),
            patch("scripts.amon.amon_cli._resolve_session_id", return_value=uuid4()),
            patch("scripts.amon.amon_cli.load_session", return_value=conversation),
            patch("scripts.amon.amon_cli.save_session") as save,
            patch(
                "scripts.amon.amon_cli._compact_history",
                side_effect=compact_history_return,
            ) as compact,
        ):
            _run_interactive(args)
        return compact, save

    def test_compact_uses_compact_history_not_the_bare_summarizer(self):
        conversation = [{"role": "user", "content": "hi"}]

        def fake_compact(convo):
            convo[:] = [{"role": "user", "content": "summarized"}]
            return True

        compact, save = self._run_compact(conversation, fake_compact)
        compact.assert_called_once()
        # _compact_history mutates in place; the mutated list is what gets saved.
        saved = save.call_args.kwargs["conversation"]
        assert saved == [{"role": "user", "content": "summarized"}]

    def test_failed_compact_does_not_overwrite_the_session(self):
        conversation = [{"role": "user", "content": "hi"}]
        compact, save = self._run_compact(conversation, lambda convo: False)
        compact.assert_called_once()
        save.assert_not_called()
