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
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            result, llm = _run(responses, registry=_registry(len))
        compact.assert_called_once()
        assert result.ok
        assert result.result == "ok"
        assert llm.call_count == 2

    def test_retries_only_once_in_a_row(self):
        responses = [RuntimeError("boom"), RuntimeError("boom again")]
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            result, _ = _run(responses, registry=_registry(len))
        assert compact.call_count == 1
        assert not result.ok
        assert "boom again" in result.error

    def test_no_retry_when_compaction_fails(self):
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = None
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
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = [{"role": "user", "content": "summary"}]
            result, _ = _run(responses, registry=_registry(lambda **kw: "ok"))
        assert compact.call_count == 2
        assert result.ok

    def test_partial_result_is_returned(self):
        responses = [
            _response(content="partial work", tool_calls=_tool_call()),
            RuntimeError("context length exceeded"),
        ]
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = None
            result, _ = _run(responses, registry=_registry(lambda **kw: "ok"))
        assert not result.ok
        assert "context length exceeded" in result.error
        assert result.result == "partial work"

    def test_failure_on_the_first_turn_does_not_propagate(self):
        with patch("scripts.amon.agent_loop.compact_conversation") as compact:
            compact.return_value = None
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


# -------------------------------------------------------- bad tool calls


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


class TestSystemPromptTemplate:
    CATALOG = SKILL_CATALOG

    def test_default_template_keeps_workspace_skills_and_mandate(self):
        out = build_system_prompt("BASE", self.CATALOG)
        assert "BASE" in out
        assert str(Path.cwd()) in out
        assert "s1" in out and "does things" in out
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
