"""Tests for the hook system: spec forms, matcher, payload, blocking."""

import json
from uuid import uuid4

from scripts.amon.hooks import HookEventName, run_hook_event
from scripts.amon.tools.agent import Agent


def _script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)
    return str(path)


def _run(specs, event=HookEventName.PRE_TOOL_USE, **kwargs):
    return run_hook_event(
        specs=specs,
        session_id=uuid4(),
        hook_event_name=event,
        cwd=".",
        **kwargs,
    )


class TestHookSpecNormalization:
    def _agent(self, hooks):
        return Agent(
            name="a",
            description="d",
            system_prompt="s",
            tools=[],
            allowed_tools=[],
            hooks=hooks,
        )

    def test_string_becomes_one_spec(self):
        agent = self._agent({"stop": "~/.amon/hooks/log.sh"})
        assert agent.hooks["stop"] == [{"command": "~/.amon/hooks/log.sh"}]

    def test_list_of_strings_becomes_specs(self):
        agent = self._agent({"stop": ["a.sh", "b.sh"]})
        assert agent.hooks["stop"] == [{"command": "a.sh"}, {"command": "b.sh"}]

    def test_objects_are_kept(self):
        spec = {"command": "a.sh", "matcher": "write_*", "timeout_ms": 500}
        agent = self._agent({"preToolUse": [spec]})
        assert agent.hooks["preToolUse"] == [spec]

    def test_no_hooks_defaults_empty(self):
        assert self._agent({}).hooks == {}


class TestHookExecution:
    def test_stdout_of_successful_hooks_is_returned(self, tmp_path):
        specs = [
            {"command": _script(tmp_path, "a.sh", "echo first")},
            {"command": _script(tmp_path, "b.sh", "echo second")},
        ]
        out, blocked = _run(specs, tool_name="shell")
        assert "first" in out and "second" in out
        assert blocked is None

    def test_missing_script_is_skipped(self):
        out, blocked = _run([{"command": "/nope/missing.sh"}], tool_name="shell")
        assert out == ""
        assert blocked is None

    def test_failing_hook_does_not_raise(self, tmp_path):
        specs = [{"command": _script(tmp_path, "f.sh", "echo bad >&2; exit 1")}]
        out, blocked = _run(specs, tool_name="shell")
        assert out == ""
        assert blocked is None

    def test_slow_hook_is_abandoned(self, tmp_path):
        specs = [{"command": _script(tmp_path, "s.sh", "sleep 5"), "timeout_ms": 100}]
        out, blocked = _run(specs, tool_name="shell")
        assert out == ""
        assert blocked is None


class TestHookMatcher:
    def test_matcher_filters_by_tool_name(self, tmp_path):
        specs = [
            {"command": _script(tmp_path, "w.sh", "echo ran"), "matcher": "write_file"}
        ]
        assert "ran" in _run(specs, tool_name="write_file")[0]
        assert _run(specs, tool_name="shell")[0] == ""

    def test_wildcard_matcher(self, tmp_path):
        specs = [
            {"command": _script(tmp_path, "w.sh", "echo ran"), "matcher": "shell*"}
        ]
        assert "ran" in _run(specs, tool_name="shell_readonly")[0]

    def test_no_matcher_runs_for_every_tool(self, tmp_path):
        specs = [{"command": _script(tmp_path, "w.sh", "echo ran")}]
        assert "ran" in _run(specs, tool_name="anything")[0]


class TestHookPayload:
    def test_event_json_arrives_on_stdin(self, tmp_path):
        specs = [{"command": _script(tmp_path, "p.sh", "cat")}]
        out, _ = _run(specs, tool_name="write_file", tool_input={"path": "x.txt"})
        payload = json.loads(out)
        assert payload["hook_event_name"] == "preToolUse"
        assert payload["tool_name"] == "write_file"
        assert payload["tool_input"] == {"path": "x.txt"}
        assert payload["cwd"] == "."

    def test_legacy_env_vars_still_work(self, tmp_path):
        specs = [
            {"command": _script(tmp_path, "e.sh", 'echo "$HOOK_EVENT_NAME/$TOOL_NAME"')}
        ]
        out, _ = _run(specs, tool_name="shell")
        assert "preToolUse/shell" in out


class TestHookBlocking:
    def test_exit_2_blocks_a_pre_tool_hook(self, tmp_path):
        specs = [{"command": _script(tmp_path, "b.sh", "echo not allowed >&2; exit 2")}]
        out, blocked = _run(specs, tool_name="write_file")
        assert blocked == "not allowed"
        assert out == ""

    def test_exit_2_does_not_block_other_events(self, tmp_path):
        specs = [{"command": _script(tmp_path, "b.sh", "echo nope >&2; exit 2")}]
        _, blocked = _run(
            specs, event=HookEventName.POST_TOOL_USE, tool_name="write_file"
        )
        assert blocked is None
