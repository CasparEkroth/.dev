"""Tests for the agent loop: output truncation, first-turn forcing, budgets."""

from unittest.mock import patch

from scripts.amon.agent_loop import run_agent, truncate_tool_output


def _response(content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    """One fake chat-completion response in the shape run_agent consumes."""
    message = {"content": content}
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


# --------------------------------------------------------------------- model


class TestModelOverride:
    def test_model_is_forwarded_to_the_llm(self):
        _, llm = _run([_response(content="hi")], model="claude-opus-5")
        assert llm.call_args_list[0].kwargs["model"] == "claude-opus-5"

    def test_no_model_forwards_none_for_the_default(self):
        _, llm = _run([_response(content="hi")])
        assert llm.call_args_list[0].kwargs["model"] is None
