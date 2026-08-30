"""Tests for the agent loop: output truncation, first-turn forcing, budgets."""

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from scripts.amon.hooks import HookEventName
from scripts.amon.agent_loop import (
    build_system_prompt,
    compact_conversation,
    run_agent,
    truncate_tool_output,
)

SKILL_CATALOG = [{"name": "s1", "path": "/skills/s1", "description": "does things"}]


def _response(content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    """One fake chat-completion response in the shape run_agent consumes."""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _tool_call(name="echo", args='{"text": "hi"}', call_id="call_1"):
    return [{"id": call_id, "function": {"name": name, "arguments": args}}]


def _registry(fn, name="echo"):
    return {
        name: {
            "schema": {"type": "function", "function": {"name": name}},
            "fn": fn,
            "requires_confirmation": False,
        }
    }


def _run(responses, registry=None, **kwargs):
    """Run the agent against a scripted list of LLM responses."""
    with patch("scripts.amon.agent_loop.call_llm_with_tools") as llm:
        llm.side_effect = responses
        result = run_agent(
            system_prompt="sys",
            user_input="task",
            tool_registry=registry if registry is not None else {},
            skill_catalog=[],
            save_session_=False,
            headless=True,
            **kwargs,
        )
    return result, llm


# ---------------------------------------------------------------- truncation


class TestPathGuardWiring:
    def test_denied_path_surfaces_as_tool_error(self, tmp_path):
        """An agent configured with deny_paths gets a blocked tool call."""
        import json
        from functools import partial

        from shared.file_handler import read_file

        secret = tmp_path / ".env"
        secret.write_text("SECRET=1\n")

        guarded = partial(
            read_file,
            allow_paths=[str(tmp_path / "**")],
            deny_paths=["**/.env"],
        )
        registry = _registry(guarded, name="read_file")

        responses = [
            _response(
                tool_calls=_tool_call(
                    name="read_file",
                    args=json.dumps({"path": str(secret)}),
                    call_id="c1",
                )
            ),
            _response(content="blocked as expected"),
        ]
        result, llm = _run(responses, registry=registry)
        assert result.ok is True
        assert result.result == "blocked as expected"
        assert result.tools_used == ["read_file"]

        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "Error:" in tool_msg["content"]
        assert (
            "PermissionError" in tool_msg["content"]
            or "deny_paths" in tool_msg["content"]
        )
        assert "SECRET=1" not in tool_msg["content"]


class TestTruncateToolOutput:
    def test_short_output_is_unchanged(self, tmp_path):
        assert truncate_tool_output("small", limit=100, spill_dir=tmp_path) == "small"

    def test_short_output_writes_no_spill_file(self, tmp_path):
        truncate_tool_output("small", limit=100, spill_dir=tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_long_output_is_bounded(self, tmp_path):
        text = "x" * 5000
        out = truncate_tool_output(text, limit=100, spill_dir=tmp_path)
        assert len(out) < len(text)
        assert "truncated" in out

    def test_keeps_head_and_tail(self, tmp_path):
        text = "HEAD" + ("m" * 5000) + "TAIL"
        out = truncate_tool_output(text, limit=100, spill_dir=tmp_path)
        assert out.startswith("HEAD")
        assert out.endswith("TAIL")

    def test_spill_file_holds_the_full_text(self, tmp_path):
        text = "y" * 5000
        out = truncate_tool_output(text, tool="shell", limit=100, spill_dir=tmp_path)
        spilled = list(tmp_path.iterdir())
        assert len(spilled) == 1
        assert spilled[0].read_text() == text
        assert str(spilled[0]) in out

    def test_creates_the_spill_dir(self, tmp_path):
        nested = tmp_path / "does" / "not" / "exist"
        truncate_tool_output("z" * 500, limit=100, spill_dir=nested)
        assert nested.is_dir()

    def test_output_exactly_at_limit_is_unchanged(self, tmp_path):
        text = "a" * 100
        assert truncate_tool_output(text, limit=100, spill_dir=tmp_path) == text

    def test_empty_output_is_unchanged(self, tmp_path):
        assert truncate_tool_output("", limit=100, spill_dir=tmp_path) == ""


class TestLoopTruncatesToolResults:
    def test_tool_message_is_truncated(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scripts.amon.agent_loop.TOOL_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("scripts.amon.agent_loop.MAX_TOOL_OUTPUT_CHARS", 200)
        big = "B" * 10_000

        captured = {}

        def echo(**kwargs):
            captured["args"] = kwargs
            return big

        responses = [
            _response(tool_calls=_tool_call()),
            _response(content="done"),
        ]
        result, llm = _run(responses, registry=_registry(echo))

        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert len(tool_msg["content"]) < len(big)
        assert "truncated" in tool_msg["content"]
        # The tool itself still received its real arguments.
        assert captured["args"] == {"text": "hi"}
        assert result.ok
        assert result.tools_used == ["echo"]
        # The full output went to the CONFIGURED spill dir, not a bound default.
        spilled = list(tmp_path.iterdir())
        assert len(spilled) == 1
        assert spilled[0].read_text() == big

    def test_short_tool_output_passes_through(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scripts.amon.agent_loop.TOOL_OUTPUT_DIR", tmp_path)
        responses = [
            _response(tool_calls=_tool_call()),
            _response(content="done"),
        ]
        _, llm = _run(responses, registry=_registry(lambda **kw: "tiny"))

        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert tool_msg["content"] == "tiny"


# ------------------------------------------------------------ first-turn tool


class TestForceFirstTool:
    def test_not_forced_by_default(self):
        _, llm = _run([_response(content="a question?")], registry=_registry(len))
        assert llm.call_args_list[0].kwargs["force_tool"] is False

    def test_forced_only_on_the_first_turn_when_enabled(self):
        responses = [
            _response(tool_calls=_tool_call()),
            _response(content="done"),
        ]
        _, llm = _run(
            responses, registry=_registry(lambda **kw: "ok"), force_first_tool=True
        )
        assert llm.call_args_list[0].kwargs["force_tool"] is True
        assert llm.call_args_list[1].kwargs["force_tool"] is False

    def test_never_forced_without_tools(self):
        _, llm = _run([_response(content="hi")], registry={}, force_first_tool=True)
        assert llm.call_args_list[0].kwargs["force_tool"] is False

    def test_text_only_first_turn_finishes_cleanly(self):
        result, _ = _run([_response(content="which model?")], registry=_registry(len))
        assert result.ok
        assert result.result == "which model?"
        assert result.turns == 1


# ------------------------------------------------------------------- budgets


class TestBudgets:
    def test_max_turns_keeps_partial_result(self):
        responses = [
            _response(content="working", tool_calls=_tool_call()) for _ in range(3)
        ]
        result, _ = _run(responses, registry=_registry(lambda **kw: "ok"), max_turns=3)
        assert not result.ok
        assert "Max turns" in result.error
        assert result.result == "working"
        assert result.turns == 3

    def test_time_budget_stops_between_turns(self):
        clock = iter([0.0, 0.0, 99.0])

        responses = [
            _response(content="working", tool_calls=_tool_call()) for _ in range(5)
        ]
        with patch("scripts.amon.agent_loop.time.monotonic", lambda: next(clock)):
            result, llm = _run(
                responses,
                registry=_registry(lambda **kw: "ok"),
                max_turns=5,
                max_runtime_s=10,
            )
        assert not result.ok
        assert "Time budget" in result.error
        assert result.turns < 5
        assert llm.call_count < 5

    def test_stop_hook_fires_when_the_budget_is_exhausted(self):
        responses = [_response(content="x", tool_calls=_tool_call()) for _ in range(2)]
        with patch("scripts.amon.agent_loop.run_hook_event") as hook:
            _run(
                responses,
                registry=_registry(lambda **kw: "ok"),
                max_turns=2,
                hooks={"stop": "/tmp/does-not-matter.sh"},
            )
        events = [c.kwargs["hook_event_name"] for c in hook.call_args_list]
        assert "stop" in [getattr(e, "value", e) for e in events]

    def test_default_max_turns_comes_from_config(self):
        import inspect

        from config import DEFAULT_MAX_TURNS

        default = inspect.signature(run_agent).parameters["max_turns"].default
        assert default == DEFAULT_MAX_TURNS

    def test_hooks_default_is_not_a_shared_mutable(self):
        """Regression: `hooks: dict = {}` on the signature is a classic
        shared-mutable-default footgun even though nothing currently mutates
        it in place. The default must be None, normalized inside the body."""
        import inspect

        default = inspect.signature(run_agent).parameters["hooks"].default
        assert default is None

    def test_omitted_hooks_does_not_crash(self):
        # Would raise on hooks.get(...) if the None -> {} normalization broke.
        result, _ = _run([_response(content="hi")], registry=_registry(len))
        assert result.ok


# --------------------------------------------------------------- compaction


class TestCompactConversation:
    def _patch(self, monkeypatch, raw):
        monkeypatch.setattr(
            "scripts.amon.agent_loop.call_llm", lambda prompt: self._seen(prompt)
        )
        monkeypatch.setattr("scripts.amon.agent_loop.parse_llm_json", lambda _: raw)

    def _seen(self, prompt):
        self.prompt = prompt
        return "irrelevant, parse_llm_json is patched"

    def test_returns_plain_messages(self, monkeypatch):
        self._patch(monkeypatch, [{"role": "user", "content": "shorter"}])
        assert compact_conversation([{"role": "user", "content": "long"}]) == [
            {"role": "user", "content": "shorter"}
        ]

    def test_strips_tool_calls_and_tool_messages(self, monkeypatch):
        self._patch(
            monkeypatch,
            [
                {
                    "role": "assistant",
                    "content": "did stuff",
                    "tool_calls": [{"id": "1"}],
                },
                {"role": "tool", "tool_call_id": "1", "content": "result"},
                {"role": "user", "content": "next"},
            ],
        )
        out = compact_conversation([{"role": "user", "content": "long"}])
        # A summarized tool_calls turn would dangle: its tool replies are gone.
        assert out == [
            {"role": "assistant", "content": "did stuff"},
            {"role": "user", "content": "next"},
        ]

    def test_unusable_json_returns_none(self, monkeypatch):
        self._patch(monkeypatch, None)
        assert compact_conversation([{"role": "user", "content": "x"}]) is None

    def test_non_list_returns_none(self, monkeypatch):
        self._patch(monkeypatch, {"role": "user", "content": "x"})
        assert compact_conversation([{"role": "user", "content": "x"}]) is None

    def test_summary_without_usable_roles_returns_none(self, monkeypatch):
        self._patch(monkeypatch, [{"role": "tool", "content": "only tools"}])
        assert compact_conversation([{"role": "user", "content": "x"}]) is None

    def test_empty_conversation_returns_none(self):
        assert compact_conversation([]) is None

    def test_prompt_carries_the_conversation(self, monkeypatch):
        self._patch(monkeypatch, [{"role": "user", "content": "s"}])
        compact_conversation([{"role": "user", "content": "MARKER"}])
        assert "MARKER" in self.prompt


class TestAutoCompaction:
    def test_not_compacted_below_the_threshold(self):
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            _run(
                [_response(tool_calls=_tool_call()), _response(content="done")],
                registry=_registry(lambda **kw: "ok"),
                compact_at_tokens=1_000_000,
            )
        compact.assert_not_called()

    def test_compacted_above_the_threshold(self):
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            _, llm = _run(
                [_response(tool_calls=_tool_call()), _response(content="done")],
                registry=_registry(lambda **kw: "ok"),
                compact_at_tokens=1,
            )
        compact.assert_called()
        second_turn = llm.call_args_list[1].args[1]
        assert second_turn[0] == {"role": "user", "content": "summary"}

    def test_tool_replies_keep_their_parent(self):
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            _, llm = _run(
                [_response(tool_calls=_tool_call()), _response(content="done")],
                registry=_registry(lambda **kw: "ok"),
                compact_at_tokens=1,
            )
        second_turn = llm.call_args_list[1].args[1]
        for index, message in enumerate(second_turn):
            if message.get("role") == "tool":
                parents = [
                    m
                    for m in second_turn[:index]
                    if m.get("role") == "assistant" and m.get("tool_calls")
                ]
                assert parents, "tool message lost the assistant turn it belongs to"

    def test_compacts_only_the_head(self):
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            _run(
                [_response(tool_calls=_tool_call()), _response(content="done")],
                registry=_registry(lambda **kw: "ok"),
                compact_at_tokens=1,
            )
        # The head handed to the summarizer stops before the tool-call turn.
        head = compact.call_args.args[0]
        assert all(not m.get("tool_calls") for m in head)

    def test_failed_summary_leaves_the_conversation_intact(self):
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = None
            _, llm = _run(
                [_response(tool_calls=_tool_call()), _response(content="done")],
                registry=_registry(lambda **kw: "ok"),
                compact_at_tokens=1,
            )
        second_turn = llm.call_args_list[1].args[1]
        assert second_turn[0] == {"role": "user", "content": "task"}


# ----------------------------------------------------------- failed llm call


class TestModelCallFailure:
    def test_recovers_by_compacting_and_retrying(self):
        responses = [RuntimeError("context length exceeded"), _response(content="ok")]
        with patch("scripts.amon.agent_loop._compact_history") as compact:
            compact.return_value = True
            result, llm = _run(responses, registry=_registry(len))
        compact.assert_called_once()
        assert result.ok
        assert result.result == "ok"
        assert llm.call_count == 2

    def test_retries_only_once_in_a_row(self):
        responses = [RuntimeError("boom"), RuntimeError("boom again")]
        with patch("scripts.amon.agent_loop._compact_history") as compact:
            compact.return_value = True
            result, _ = _run(responses, registry=_registry(len))
        assert compact.call_count == 1
        assert not result.ok
        assert "boom again" in result.error

    def test_no_retry_when_compaction_fails(self):
        with patch("scripts.amon.agent_loop._compact_history") as compact:
            compact.return_value = False
            result, llm = _run([RuntimeError("boom")], registry=_registry(len))
        assert llm.call_count == 1
        assert not result.ok

    def test_recovery_is_available_again_after_a_success(self):
        responses = [
            RuntimeError("first"),
            _response(content="mid", tool_calls=_tool_call()),
            RuntimeError("second"),
            _response(content="done"),
        ]
        with patch("scripts.amon.agent_loop._compact_history") as compact:
            compact.return_value = True
            result, _ = _run(responses, registry=_registry(lambda **kw: "ok"))
        assert compact.call_count == 2
        assert result.ok

    def test_partial_result_is_returned(self):
        responses = [
            _response(content="partial work", tool_calls=_tool_call()),
            RuntimeError("context length exceeded"),
        ]
        with patch("scripts.amon.agent_loop._compact_history") as compact:
            compact.return_value = False
            result, _ = _run(responses, registry=_registry(lambda **kw: "ok"))
        assert not result.ok
        assert "context length exceeded" in result.error
        assert result.result == "partial work"

    def test_failure_on_the_first_turn_does_not_propagate(self):
        with patch("scripts.amon.agent_loop._compact_history") as compact:
            compact.return_value = False
            result, _ = _run([RuntimeError("boom")], registry=_registry(len))
        assert not result.ok
        assert result.result is None
        assert "boom" in result.error

    def test_stop_hook_fires_and_session_persists(self):
        with (
            patch("scripts.amon.agent_loop.run_hook_event") as hook,
            patch("scripts.amon.agent_loop.save_session") as save,
        ):
            save.return_value = None
            with patch("scripts.amon.agent_loop.call_llm_with_tools") as llm:
                llm.side_effect = [RuntimeError("boom")]
                run_agent(
                    system_prompt="sys",
                    user_input="task",
                    tool_registry={},
                    skill_catalog=[],
                    save_session_=True,
                    headless=True,
                    hooks={"stop": "/tmp/does-not-matter.sh"},
                )
        save.assert_called()
        events = [c.kwargs["hook_event_name"] for c in hook.call_args_list]
        assert "stop" in [getattr(e, "value", e) for e in events]

    def test_context_length_failure_can_fall_back_to_hard_trim(self):
        with (
            patch("scripts.amon.agent_loop._compact_history") as compact,
            patch("scripts.amon.agent_loop._force_hard_trim") as hard_trim,
        ):
            compact.return_value = False
            hard_trim.return_value = True
            result, llm = _run(
                [RuntimeError("context_length_exceeded"), _response(content="ok")],
                registry=_registry(len),
            )
        assert compact.call_count == 1
        assert hard_trim.call_count == 1
        assert result.ok
        assert llm.call_count == 2

    def test_compact_history_keeps_assistant_tool_calls_with_their_tool_messages(self):
        from scripts.amon.agent_loop import _compact_history

        conversation = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": "do work",
                "tool_calls": [
                    {"id": "call_a", "function": {"name": "echo", "arguments": "{}"}},
                    {"id": "call_b", "function": {"name": "echo", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "result a"},
            {"role": "tool", "tool_call_id": "call_b", "content": "result b"},
            {"role": "user", "content": "more context"},
        ]

        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            assert _compact_history(conversation) is True

        assert compact.call_args.args[0] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ]
        assert conversation[0] == {"role": "user", "content": "summary"}

    def test_compact_history_does_not_orphan_tool_calls(self):
        from scripts.amon.agent_loop import _compact_history

        conversation = [
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": "call tools",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "echo", "arguments": "{}"}},
                    {"id": "call_2", "function": {"name": "echo", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "result 1"},
        ]

        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            assert _compact_history(conversation) is True

        assert conversation[0] == {"role": "user", "content": "summary"}
        assert all(
            not (m.get("role") == "assistant" and m.get("tool_calls"))
            for m in conversation
        )

    def test_compact_history_drops_unfinished_tool_turns_before_compacting(self):
        from scripts.amon.agent_loop import _compact_history

        conversation = [
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": "call tools",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "echo", "arguments": "{}"}},
                    {"id": "call_2", "function": {"name": "echo", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "result 1"},
            {"role": "user", "content": "later"},
        ]

        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            assert _compact_history(conversation) is True

        compacted_input = compact.call_args.args[0]
        assert all(
            m.get("role") != "assistant" or not m.get("tool_calls")
            for m in compacted_input
        )
        assert conversation[0] == {"role": "user", "content": "summary"}


# ---------------------------------------------------------------------- hooks


class TestHookIntegration:
    def _hook_returning(self, stdout, blocked=None):
        return patch(
            "scripts.amon.agent_loop.run_hook_event", return_value=(stdout, blocked)
        )

    def test_agent_spawn_output_reaches_the_model(self):
        with self._hook_returning("python: /venv/bin/python3"):
            _, llm = _run(
                [_response(content="hi")],
                hooks={"agentSpawn": [{"command": "probe.sh"}]},
            )
        messages = llm.call_args_list[0].args[1]
        assert any("/venv/bin/python3" in m.get("content", "") for m in messages)

    def test_injected_output_is_persisted(self):
        with (
            self._hook_returning("env facts"),
            patch("scripts.amon.agent_loop.save_session") as save,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            save.return_value = None
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=True,
                headless=True,
                hooks={"agentSpawn": [{"command": "probe.sh"}]},
            )
        persisted = save.call_args.args[0]
        assert any("env facts" in m.get("content", "") for m in persisted)

    def test_empty_hook_output_adds_no_message(self):
        with self._hook_returning("  \n"):
            _, llm = _run(
                [_response(content="hi")],
                hooks={"agentSpawn": [{"command": "probe.sh"}]},
            )
        messages = llm.call_args_list[0].args[1]
        # Captured list is mutated in place, so the reply is expected — but no
        # injected hook message between them.
        assert [m["content"] for m in messages] == ["task", "hi"]

    def test_agent_spawn_skipped_when_session_has_history(self):
        with (
            patch("scripts.amon.agent_loop.load_session") as load,
            patch("scripts.amon.agent_loop.run_hook_event") as hook,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            load.return_value = [{"role": "user", "content": "earlier"}]
            hook.return_value = ("", None)
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=False,
                headless=True,
                session_id=uuid4(),
                hooks={"agentSpawn": [{"command": "probe.sh"}]},
            )
        events = [c.kwargs["hook_event_name"] for c in hook.call_args_list]
        assert HookEventName.AGENT_SPAWN not in events

    def test_blocked_tool_is_not_executed(self):
        called = []

        def tool(**kwargs):
            called.append(kwargs)
            return "ran"

        with self._hook_returning("", "writes are not allowed here"):
            result, llm = _run(
                [_response(tool_calls=_tool_call()), _response(content="understood")],
                registry=_registry(tool),
                hooks={"preToolUse": [{"command": "guard.sh"}]},
            )
        assert called == []
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "writes are not allowed here" in tool_msg["content"]
        assert result.ok


# --------------------------------------------- orphaned tool cycle on load


class TestSanitizeHistoryOnLoad:
    """A prior run interrupted between persisting tool_calls and appending
    the matching tool replies leaves an incomplete cycle on disk. Loading it
    straight into a new call breaks the API request."""

    def test_dangling_tool_calls_are_stripped_from_loaded_history(self):
        orphaned_history = [
            {"role": "user", "content": "earlier task"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "echo", "arguments": "{}"}}
                ],
            },
            # No matching {"role": "tool", "tool_call_id": "c1", ...} — the
            # run was interrupted before the tool finished.
        ]
        with (
            patch("scripts.amon.agent_loop.load_session") as load,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            load.return_value = orphaned_history
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=False,
                headless=True,
                session_id=uuid4(),
            )
        sent = llm.call_args_list[0].args[1]
        # The orphaned assistant tool_calls message is gone...
        assert not any(m.get("tool_calls") for m in sent)
        # ...but the user message before it, and this turn's new input,
        # both survive — only the incomplete cycle is stripped.
        contents = [m.get("content") for m in sent]
        assert "earlier task" in contents
        assert "task" in contents

    def test_complete_history_is_untouched(self):
        complete_history = [
            {"role": "user", "content": "earlier task"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "echo", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "done"},
        ]
        with (
            patch("scripts.amon.agent_loop.load_session") as load,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            load.return_value = complete_history
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=False,
                headless=True,
                session_id=uuid4(),
            )
        sent = llm.call_args_list[0].args[1]
        assert any(m.get("tool_calls") for m in sent)
        assert any(m.get("role") == "tool" for m in sent)


# ------------------------------------------------------- todo resume/inject


class TestEventLog:
    """Optional structured event log (AMON_EVENTS) — off unless a caller
    passes event_log, and never touches time.monotonic when it's None."""

    def test_turn_and_tool_events_are_logged(self):
        events = []
        _run(
            [_response(tool_calls=_tool_call()), _response(content="done")],
            registry=_registry(lambda **kw: "ok"),
            event_log=events.append,
        )
        kinds = [e["event"] for e in events]
        assert kinds.count("turn") == 2
        assert "tool_call" in kinds
        assert "tool_result" in kinds

    def test_turn_event_has_latency_and_usage(self):
        events = []
        _run(
            [_response(content="done", prompt_tokens=7, completion_tokens=3)],
            registry=_registry(lambda **kw: "ok"),
            event_log=events.append,
        )
        turn_events = [e for e in events if e["event"] == "turn"]
        assert len(turn_events) == 1
        assert turn_events[0]["usage"]["prompt_tokens"] == 7
        assert isinstance(turn_events[0]["latency_s"], float)

    def test_tool_result_event_has_output_chars(self):
        events = []
        _run(
            [_response(tool_calls=_tool_call()), _response(content="done")],
            registry=_registry(lambda **kw: "a real result"),
            event_log=events.append,
        )
        result_events = [e for e in events if e["event"] == "tool_result"]
        assert len(result_events) == 1
        assert result_events[0]["output_chars"] == len("a real result")
        assert result_events[0]["name"] == "echo"

    def test_compact_event_logged_on_threshold_trigger(self):
        events = []
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            _run(
                [_response(tool_calls=_tool_call()), _response(content="done")],
                registry=_registry(lambda **kw: "ok"),
                compact_at_tokens=1,
                event_log=events.append,
            )
        compact_events = [e for e in events if e["event"] == "compact"]
        assert len(compact_events) == 1
        assert compact_events[0]["trigger"] == "threshold"
        assert compact_events[0]["method"] == "summary"

    def test_events_carry_session_id_when_present(self):
        events = []
        sid = uuid4()
        with (
            patch("scripts.amon.agent_loop.load_session", return_value=[]),
            patch("scripts.amon.agent_loop.save_session", return_value=sid),
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=True,
                headless=True,
                session_id=sid,
                event_log=events.append,
            )
        assert all(e["session_id"] == str(sid) for e in events)

    def test_monotonic_not_called_extra_times_when_event_log_is_none(self):
        # Regression: adding timing must not perturb time.monotonic call
        # counts for anything mocking the clock (e.g. TestBudgets below).
        clock = iter([0.0, 0.0, 99.0])
        responses = [
            _response(content="working", tool_calls=_tool_call()) for _ in range(5)
        ]
        with patch("scripts.amon.agent_loop.time.monotonic", lambda: next(clock)):
            result, _ = _run(
                responses,
                registry=_registry(lambda **kw: "ok"),
                max_turns=5,
                max_runtime_s=10,
            )
        assert not result.ok
        assert "Time budget" in result.error


class TestSessionInfo:
    """A new session records {agent, preview} once, for /sessions and
    --resume; a resumed session doesn't re-save it on every turn."""

    def test_new_session_saves_agent_and_preview(self):
        sid = uuid4()
        with (
            patch("scripts.amon.agent_loop.load_session", return_value=[]),
            patch("scripts.amon.agent_loop.save_session", return_value=sid),
            patch("scripts.amon.agent_loop.save_session_info") as save_info,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="fix the login bug please",
                tool_registry={},
                skill_catalog=[],
                save_session_=True,
                headless=True,
                session_id=sid,
                agent_name="dev",
            )
        save_info.assert_called_once()
        assert save_info.call_args.args[0] == sid
        assert save_info.call_args.kwargs["agent"] == "dev"
        assert "fix the login bug" in save_info.call_args.kwargs["preview"]

    def test_resumed_session_does_not_resave_info(self):
        with (
            patch("scripts.amon.agent_loop.load_session") as load,
            patch("scripts.amon.agent_loop.save_session", return_value=uuid4()),
            patch("scripts.amon.agent_loop.save_session_info") as save_info,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            load.return_value = [{"role": "user", "content": "earlier"}]
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="continue please",
                tool_registry={},
                skill_catalog=[],
                save_session_=True,
                headless=True,
                session_id=uuid4(),
                agent_name="dev",
            )
        save_info.assert_not_called()

    def test_no_session_id_never_saves_info(self):
        with (
            patch("scripts.amon.agent_loop.save_session_info") as save_info,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=False,
                headless=True,
                agent_name="dev",
            )
        save_info.assert_not_called()


class TestTodoResumeInjection:
    """A resumed session with a saved checklist should see it again."""

    def test_existing_checklist_is_injected_on_resume(self):
        with (
            patch("scripts.amon.agent_loop.load_session") as load,
            patch("scripts.amon.agent_loop.get_todos") as get_todos,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            load.return_value = [{"role": "user", "content": "earlier"}]
            get_todos.return_value = [
                {"content": "step one", "status": "completed"},
                {"content": "step two", "status": "in_progress"},
            ]
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=False,
                headless=True,
                session_id=uuid4(),
            )
        messages = llm.call_args_list[0].args[1]
        injected = [
            m["content"] for m in messages if "step two" in m.get("content", "")
        ]
        assert injected
        assert "step one" in injected[0]
        assert "Resuming" in injected[0]

    def test_no_injection_when_no_saved_checklist(self):
        with (
            patch("scripts.amon.agent_loop.load_session") as load,
            patch("scripts.amon.agent_loop.get_todos") as get_todos,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            load.return_value = [{"role": "user", "content": "earlier"}]
            get_todos.return_value = []
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=False,
                headless=True,
                session_id=uuid4(),
            )
        # The captured list is mutated in place, so the assistant reply is
        # present too — the point is no checklist message got inserted.
        messages = llm.call_args_list[0].args[1]
        assert [m["content"] for m in messages] == ["earlier", "task", "hi"]

    def test_no_injection_on_a_brand_new_session(self):
        """Empty history means it's the first turn — nothing to resume yet."""
        with (
            patch("scripts.amon.agent_loop.load_session") as load,
            patch("scripts.amon.agent_loop.get_todos") as get_todos,
            patch("scripts.amon.agent_loop.call_llm_with_tools") as llm,
        ):
            load.return_value = []
            get_todos.return_value = [{"content": "stale", "status": "pending"}]
            llm.side_effect = [_response(content="hi")]
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry={},
                skill_catalog=[],
                save_session_=False,
                headless=True,
                session_id=uuid4(),
            )
        get_todos.assert_not_called()
        messages = llm.call_args_list[0].args[1]
        assert not any("stale" in m.get("content", "") for m in messages)

    def test_no_injection_or_lookup_without_a_session_id(self):
        with (patch("scripts.amon.agent_loop.get_todos") as get_todos,):
            _run([_response(content="hi")])
        get_todos.assert_not_called()


# -------------------------------------------------------- bad tool calls


class TestConfirmationOutcomes:
    """confirm_fn may return a bare bool or (allowed, reason).

    Uses run_agent directly with headless=False: the _run() helper always
    forces headless=True, which short-circuits before confirm_fn is ever
    called (see TestHeadlessShortCircuitsConfirm below) — not useful here.
    """

    def _registry_confirmable(self, fn):
        return {
            "echo": {
                "schema": {"type": "function", "function": {"name": "echo"}},
                "fn": fn,
                "requires_confirmation": True,
            }
        }

    def _run_interactive_style(self, responses, registry, confirm_fn):
        with patch("scripts.amon.agent_loop.call_llm_with_tools") as llm:
            llm.side_effect = responses
            result = run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry=registry,
                skill_catalog=[],
                save_session_=False,
                headless=False,
                confirm_fn=confirm_fn,
                stream_actions=lambda *a, **kw: None,
            )
        return result, llm

    def test_bare_bool_true_still_runs_the_tool(self):
        called = []
        result, _ = self._run_interactive_style(
            [_response(tool_calls=_tool_call(name="echo")), _response(content="done")],
            self._registry_confirmable(lambda **kw: called.append(kw) or "ran"),
            confirm_fn=lambda name, args: True,
        )
        assert called
        assert result.ok

    def test_bare_bool_false_denies_without_a_reason(self):
        called = []
        result, llm = self._run_interactive_style(
            [
                _response(tool_calls=_tool_call(name="echo")),
                _response(content="understood"),
            ],
            self._registry_confirmable(lambda **kw: called.append(kw) or "ran"),
            confirm_fn=lambda name, args: False,
        )
        assert called == []
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "User denied permission" in tool_msg["content"]
        assert "Reason:" not in tool_msg["content"]

    def test_tuple_true_runs_the_tool(self):
        called = []
        result, _ = self._run_interactive_style(
            [_response(tool_calls=_tool_call(name="echo")), _response(content="done")],
            self._registry_confirmable(lambda **kw: called.append(kw) or "ran"),
            confirm_fn=lambda name, args: (True, None),
        )
        assert called
        assert result.ok

    def test_tuple_false_with_reason_reaches_the_model(self):
        called = []
        result, llm = self._run_interactive_style(
            [
                _response(tool_calls=_tool_call(name="echo")),
                _response(content="understood"),
            ],
            self._registry_confirmable(lambda **kw: called.append(kw) or "ran"),
            confirm_fn=lambda name, args: (False, "not safe to run right now"),
        )
        assert called == []
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "User denied permission" in tool_msg["content"]
        assert "Reason: not safe to run right now" in tool_msg["content"]


class TestHeadlessShortCircuitsConfirm:
    def test_headless_never_calls_confirm_fn(self):
        confirm_calls = []
        registry = {
            "echo": {
                "schema": {"type": "function", "function": {"name": "echo"}},
                "fn": lambda **kw: "ran",
                "requires_confirmation": True,
            }
        }
        result, llm = _run(
            [_response(tool_calls=_tool_call(name="echo")), _response(content="ok")],
            registry=registry,
            confirm_fn=lambda name, args: confirm_calls.append(1) or True,
        )
        assert confirm_calls == []
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "headless mode" in tool_msg["content"]


class TestBadToolCalls:
    """Unknown names / malformed args must not kill the loop."""

    def test_unknown_tool_continues_and_reports(self):
        called = []

        def tool(**kwargs):
            called.append(kwargs)
            return "ran"

        post_hooks = []

        def fake_hook(**kwargs):
            if kwargs.get("hook_event_name") == HookEventName.POST_TOOL_USE:
                post_hooks.append(kwargs)
            return ("", None)

        with patch("scripts.amon.agent_loop.run_hook_event", side_effect=fake_hook):
            result, llm = _run(
                [
                    _response(tool_calls=_tool_call(name="write")),
                    _response(content="recovered"),
                ],
                registry=_registry(tool, name="echo"),
            )
        assert called == []
        assert result.ok
        assert result.result == "recovered"
        assert llm.call_count == 2
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "Unknown tool 'write'" in tool_msg["content"]
        assert "echo" in tool_msg["content"]
        assert len(post_hooks) == 1

    def test_malformed_args_json_continues_and_reports(self):
        called = []

        def tool(**kwargs):
            called.append(kwargs)
            return "ran"

        post_hooks = []

        def fake_hook(**kwargs):
            if kwargs.get("hook_event_name") == HookEventName.POST_TOOL_USE:
                post_hooks.append(kwargs)
            return ("", None)

        with patch("scripts.amon.agent_loop.run_hook_event", side_effect=fake_hook):
            result, llm = _run(
                [
                    _response(tool_calls=_tool_call(args="{not json")),
                    _response(content="recovered"),
                ],
                registry=_registry(tool),
            )
        assert called == []
        assert result.ok
        assert result.result == "recovered"
        assert llm.call_count == 2
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "Invalid arguments JSON" in tool_msg["content"]
        assert len(post_hooks) == 1


# ------------------------------------------------------------ prompt template


class TestFileEventLog:
    def test_delegates_to_append_event_with_the_events_session_id(self):
        from scripts.amon.agent_loop import file_event_log

        with patch("scripts.amon.agent_loop.append_event") as append:
            file_event_log({"session_id": "abc-123", "event": "turn"})
        append.assert_called_once_with(
            "abc-123", {"session_id": "abc-123", "event": "turn"}
        )

    def test_drops_events_with_no_session_id(self):
        from scripts.amon.agent_loop import file_event_log

        with patch("scripts.amon.agent_loop.append_event") as append:
            file_event_log({"event": "turn", "session_id": None})
        append.assert_not_called()


class TestSystemPromptTemplate:
    CATALOG = SKILL_CATALOG

    def test_default_template_keeps_workspace_skills_and_mandate(self):
        out = build_system_prompt("BASE", self.CATALOG)
        assert "BASE" in out
        assert str(Path.cwd()) in out
        assert "s1" in out and "does things" in out
        assert "load_skill" in out

    def test_skill_mandate_does_not_demand_first_tool_call(self):
        # Regression: the old wording ("your FIRST tool call MUST be
        # load_skill...") directly contradicted default/dev's own
        # "call todo_write ... before your first other tool call" rule
        # whenever both applied to the same request.
        out = build_system_prompt(
            "call todo_write with the full checklist before your first "
            "other tool call",
            self.CATALOG,
        )
        assert "FIRST tool call MUST be" not in out
        assert "before your first other tool call" in out
        assert "load_skill" in out

    def test_custom_template_can_drop_the_mandate(self):
        out = build_system_prompt("BASE", self.CATALOG, "{prompt}\n\nSkills:\n{skills}")
        assert "load_skill" not in out
        assert "BASE" in out
        assert "s1" in out

    def test_custom_template_may_ignore_placeholders(self):
        assert build_system_prompt("BASE", self.CATALOG, "fixed prompt") == (
            "fixed prompt"
        )

    def test_unknown_placeholder_raises_at_assembly(self):
        with pytest.raises(KeyError):
            build_system_prompt("BASE", self.CATALOG, "{nope}")

    def test_run_agent_uses_the_template(self):
        _, llm = _run(
            [_response(content="hi")],
            system_prompt_template="ONLY: {prompt}",
        )
        assert llm.call_args_list[0].args[0] == "ONLY: sys"


class TestStreamActionsHeadlessOverride:
    """Regression: operator precedence used to parse `stream_actions =
    stream_actions or stream_action if not headless else None` as
    `(stream_actions or stream_action) if not headless else None`, which
    discarded ANY caller-provided stream_actions whenever headless=True —
    silently breaking run_task's AMON_STREAM support entirely."""

    def test_caller_stream_actions_is_used_in_headless_mode(self):
        # _run() already forces headless=True.
        seen = []
        _run(
            [_response(tool_calls=_tool_call()), _response(content="done")],
            registry=_registry(lambda **kw: "ok"),
            stream_actions=lambda event, data: seen.append(event),
        )
        assert "tool_call" in seen
        assert "tool_result" in seen

    def test_no_stream_actions_in_headless_mode_stays_silent(self):
        # Default (no caller override) must still be None in headless mode —
        # only an explicit override should turn streaming on.
        with patch("scripts.amon.terminal.stream_action") as default_stream:
            _run(
                [_response(tool_calls=_tool_call()), _response(content="done")],
                registry=_registry(lambda **kw: "ok"),
            )
        default_stream.assert_not_called()

    def test_default_stream_action_used_when_not_headless_and_no_override(self):
        with patch("scripts.amon.terminal.stream_action") as default_stream:
            run_agent(
                system_prompt="sys",
                user_input="task",
                tool_registry=_registry(lambda **kw: "ok"),
                skill_catalog=[],
                save_session_=False,
                headless=False,
                confirm_fn=lambda name, args: True,
            )
        default_stream.assert_not_called()  # no tool call in this run
        # Confirm it's actually wired in by triggering a tool call turn:
        with patch("scripts.amon.terminal.stream_action") as default_stream:
            with patch("scripts.amon.agent_loop.call_llm_with_tools") as llm:
                llm.side_effect = [
                    _response(tool_calls=_tool_call()),
                    _response(content="done"),
                ]
                run_agent(
                    system_prompt="sys",
                    user_input="task",
                    tool_registry=_registry(lambda **kw: "ok"),
                    skill_catalog=[],
                    save_session_=False,
                    headless=False,
                    confirm_fn=lambda name, args: True,
                )
        assert default_stream.called


class TestModelOverride:
    def test_model_is_forwarded_to_the_llm(self):
        _, llm = _run([_response(content="hi")], model="claude-opus-5")
        assert llm.call_args_list[0].kwargs["model"] == "claude-opus-5"

    def test_no_model_forwards_none_for_the_default(self):
        _, llm = _run([_response(content="hi")])
        assert llm.call_args_list[0].kwargs["model"] is None


class TestMaxToolOutputChars:
    def test_raised_cap_keeps_output_global_would_cut(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scripts.amon.agent_loop.MAX_TOOL_OUTPUT_CHARS", 50)
        monkeypatch.setattr("scripts.amon.agent_loop.TOOL_OUTPUT_DIR", tmp_path)

        def tool(**kwargs):
            return "x" * 200

        result, llm = _run(
            [_response(tool_calls=_tool_call()), _response(content="done")],
            registry=_registry(tool),
            max_tool_output_chars=500,
        )
        assert result.ok
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert tool_msg["content"] == "x" * 200
        assert "truncated" not in tool_msg["content"]

    def test_default_cap_still_truncates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scripts.amon.agent_loop.MAX_TOOL_OUTPUT_CHARS", 50)
        monkeypatch.setattr("scripts.amon.agent_loop.TOOL_OUTPUT_DIR", tmp_path)

        def tool(**kwargs):
            return "y" * 200

        _, llm = _run(
            [_response(tool_calls=_tool_call()), _response(content="done")],
            registry=_registry(tool),
        )
        conversation = llm.call_args_list[1].args[1]
        tool_msg = next(m for m in conversation if m.get("role") == "tool")
        assert "truncated" in tool_msg["content"]
        # Notice text can exceed the raw cap; the body must not be the full dump.
        assert tool_msg["content"] != "y" * 200
        assert tool_msg["content"].count("y") < 200
