import asyncio
import json
from unittest.mock import patch, MagicMock

from scripts.amon.agent_loop import AgentResult
from scripts.amon.tools.agent import (
    Agent,
    load_ready_agents,
    run_jobs,
)


def test_agent_from_file(tmp_path):
    config = {
        "name": "test_agent",
        "description": "A test agent",
        "system_prompt": "You are a test.",
        "tools": ["tool1"],
        "allowed_tools": ["tool1"],
        "max_turns": 5,
    }
    config_file = tmp_path / "test.json"
    config_file.write_text(json.dumps(config))

    agent = Agent.from_file(config_file)
    assert agent.name == "test_agent"
    assert agent.max_turns == 5


def test_load_ready_agents(tmp_path, monkeypatch):
    from pathlib import Path

    agents_dir = tmp_path / ".amon" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "mock_agent.json").write_text(
        json.dumps(
            {
                "name": "mock_agent",
                "description": "mock",
                "system_prompt": "hi",
                "tools": [],
                "allowed_tools": [],
            }
        )
    )

    monkeypatch.chdir(tmp_path)

    missing = tmp_path / "missing-agents"
    with (patch("scripts.amon.tools.agent.Path") as path_cls,):
        # Keep Path constructor real for Agent.from_file internals via side_effect,
        # but control the three discovery roots.
        real_path = Path

        def ctor(arg=None):
            if arg is None:
                return real_path()
            return real_path(arg)

        path_cls.side_effect = ctor
        path_cls.home.return_value = missing
        path_cls.cwd.return_value = tmp_path

        # system_path = Path("/etc/.amon/agents") should also miss
        original_side_effect = ctor

        def ctor_with_system(arg=None):
            if arg == "/etc/.amon/agents":
                return missing
            return original_side_effect(arg)

        path_cls.side_effect = ctor_with_system
        agents = load_ready_agents()
        assert "mock_agent" in agents
        assert agents["mock_agent"].name == "mock_agent"


def test_load_ready_agents_warns_on_name_stem_mismatch(tmp_path, monkeypatch, caplog):
    from pathlib import Path

    agents_dir = tmp_path / ".amon" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "renamed_file.json").write_text(
        json.dumps(
            {
                "name": "original_name",
                "description": "mock",
                "system_prompt": "hi",
                "tools": [],
                "allowed_tools": [],
            }
        )
    )

    monkeypatch.chdir(tmp_path)

    missing = tmp_path / "missing-agents"
    with (patch("scripts.amon.tools.agent.Path") as path_cls,):
        real_path = Path

        def ctor(arg=None):
            if arg is None:
                return real_path()
            if arg == "/etc/.amon/agents":
                return missing
            return real_path(arg)

        path_cls.side_effect = ctor
        path_cls.home.return_value = missing
        path_cls.cwd.return_value = tmp_path

        with caplog.at_level("WARNING"):
            agents = load_ready_agents()

    # Filename stem still wins as the map key...
    assert "renamed_file" in agents
    assert agents["renamed_file"].name == "original_name"
    # ...but the mismatch is surfaced instead of silently swallowed.
    assert any(
        "renamed_file" in r.getMessage() and "original_name" in r.getMessage()
        for r in caplog.records
    )


def test_agent_result_to_dict():
    result = AgentResult(
        ok=True,
        result="hello",
        error=None,
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        turns=2,
        tools_used=["read_file"],
        session_id="abc",
    )
    assert result.to_dict() == {
        "ok": True,
        "result": "hello",
        "error": None,
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "turns": 2,
        "tools_used": ["read_file"],
        "session_id": "abc",
    }


def test_agent_new_fields_round_trip(tmp_path):
    config = {
        "name": "planner",
        "description": "A planner",
        "system_prompt": "You plan.",
        "tools": ["shell"],
        "allowed_tools": ["shell"],
        "max_turns": 60,
        "force_first_tool": True,
        "max_runtime_s": 900,
        "model": "claude-opus-5",
        "mcp_servers": {
            "git": {"command": "mcp-server-git", "args": ["--stdio"]},
            "remote": {"url": "https://mcp.example.com/sse"},
        },
    }
    config_file = tmp_path / "planner.json"
    config_file.write_text(json.dumps(config))

    agent = Agent.from_file(config_file)
    assert agent.max_turns == 60
    assert agent.force_first_tool is True
    assert agent.max_runtime_s == 900
    assert agent.model == "claude-opus-5"
    assert agent.mcp_servers["git"]["command"] == "mcp-server-git"
    assert agent.mcp_servers["remote"]["url"] == "https://mcp.example.com/sse"


def test_agent_new_field_defaults(tmp_path):
    from config import DEFAULT_MAX_TURNS

    config = {
        "name": "minimal",
        "description": "minimal",
        "system_prompt": "hi",
        "tools": [],
        "allowed_tools": [],
    }
    config_file = tmp_path / "minimal.json"
    config_file.write_text(json.dumps(config))

    agent = Agent.from_file(config_file)
    assert agent.max_turns == DEFAULT_MAX_TURNS
    assert agent.force_first_tool is False
    assert agent.max_runtime_s is None
    assert agent.model is None
    assert agent.mcp_servers == {}
    assert agent.allow_paths == []
    assert agent.deny_paths == []
    assert agent.denied_commands == []


def test_run_task_forwards_new_fields():
    agent = Agent(
        name="a",
        description="d",
        system_prompt="s",
        tools=[],
        allowed_tools=[],
        max_turns=42,
        force_first_tool=True,
        max_runtime_s=123.0,
        model="pinned-model",
        max_tool_output_chars=50_000,
        mcp_servers={"git": {"command": "mcp-server-git"}},
    )

    with patch("scripts.amon.tools.agent.run_agent") as run:
        run.return_value = AgentResult(ok=True, result="done")
        asyncio.run(agent.run_task("task"))

    kwargs = run.call_args.kwargs
    assert kwargs["max_turns"] == 42
    assert kwargs["force_first_tool"] is True
    assert kwargs["max_runtime_s"] == 123.0
    assert kwargs["model"] == "pinned-model"
    assert kwargs["max_tool_output_chars"] == 50_000
    assert kwargs["stream_actions"] is None
    assert kwargs["agent_name"] == "a"
    # mcp_servers is a stub: accepted on the config, not yet wired into a run.
    assert "mcp_servers" not in kwargs


def test_run_task_streams_when_amon_stream_set(monkeypatch):
    agent = Agent(
        name="a",
        description="d",
        system_prompt="s",
        tools=[],
        allowed_tools=[],
    )
    monkeypatch.setenv("AMON_STREAM", "1")
    with patch("scripts.amon.tools.agent.run_agent") as run:
        run.return_value = AgentResult(ok=True, result="done")
        asyncio.run(agent.run_task("task"))
    assert run.call_args.kwargs["stream_actions"] is not None


def test_get_registry_does_not_leak_permissions_between_agents():
    from scripts.amon.tools.registry import get_registry, tool_registry

    permissive = get_registry(tools=["shell"], allowed_tools=["shell"])
    restrictive = get_registry(tools=["shell"], allowed_tools=[])

    assert permissive["shell"]["requires_confirmation"] is False
    # The restrictive agent must still confirm, even though a permissive one ran.
    assert restrictive["shell"]["requires_confirmation"] is True
    # And the shared global is untouched by either call.
    assert tool_registry["shell"]["requires_confirmation"] is True


def test_get_registry_shares_schema_and_fn():
    from scripts.amon.tools.registry import get_registry, tool_registry

    # shell/shell_readonly always get a sticky-cwd wrapper (TestCwdStickiness
    # covers that) — use a tool with no such wrapping to check the plain
    # "untouched by default" case.
    entry = get_registry(tools=["load_skill"], allowed_tools=["load_skill"])[
        "load_skill"
    ]
    assert entry["fn"] is tool_registry["load_skill"]["fn"]
    assert entry["schema"] is tool_registry["load_skill"]["schema"]


def test_wildcard_bare_string_normalized_but_not_expanded(tmp_path):
    """ "*" becomes ["*"] at load time, but stays unexpanded.

    Regression for the bug where eager expansion at Agent-load time ran
    before spawn_agents was registered, so wildcard agents silently never
    got it. Expansion now happens in get_registry instead (see below).
    """
    config = {
        "name": "a",
        "description": "d",
        "system_prompt": "hi",
        "tools": "*",
        "allowed_tools": "*",
    }
    config_file = tmp_path / "a.json"
    config_file.write_text(json.dumps(config))

    agent = Agent.from_file(config_file)
    assert agent.tools == ["*"]
    assert agent.allowed_tools == ["*"]


def test_get_registry_expands_wildcard_at_call_time_including_spawn_agents():
    from scripts.amon.tools.registry import get_registry, tool_registry

    reg = get_registry(tools=["*"], allowed_tools=["*"])
    assert set(reg) == set(tool_registry)
    assert "spawn_agents" in reg
    assert reg["spawn_agents"]["requires_confirmation"] is False


def test_get_registry_selection_rules():
    from scripts.amon.tools.registry import get_registry

    assert get_registry() == {}
    assert get_registry(tools=["not_a_tool"]) == {}
    # No allowed_tools means everything needs confirmation.
    every = get_registry(tools=["shell", "read_file"])
    assert set(every) == {"shell", "read_file"}
    assert all(v["requires_confirmation"] for v in every.values())


def test_agent_path_fields_round_trip(tmp_path):
    config = {
        "name": "scoped",
        "description": "scoped",
        "system_prompt": "hi",
        "tools": ["read_file", "shell"],
        "allowed_tools": ["read_file"],
        "allow_paths": ["/tmp/work/**"],
        "deny_paths": ["**/.env"],
        "denied_commands": ["rm", "curl"],
    }
    config_file = tmp_path / "scoped.json"
    config_file.write_text(json.dumps(config))

    agent = Agent.from_file(config_file)
    assert agent.allow_paths == ["/tmp/work/**"]
    assert agent.deny_paths == ["**/.env"]
    assert agent.denied_commands == ["rm", "curl"]


def test_get_registry_binds_path_guards_without_schema_leak(tmp_path):
    from functools import partial

    from scripts.amon.tools.registry import get_registry, tool_registry

    allowed = tmp_path / "ok"
    allowed.mkdir()
    (allowed / "f.txt").write_text("hi\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("nope\n")

    reg = get_registry(
        tools=["read_file", "shell", "load_skill"],
        allowed_tools=["read_file", "shell", "load_skill"],
        allow_paths=[str(allowed / "**")],
        deny_paths=[str(secret)],
        denied_commands=["rm"],
    )

    # Guards must not appear in the model-facing schema.
    for name in ("read_file", "shell"):
        params = reg[name]["schema"]["function"]["parameters"]["properties"]
        assert "allow_paths" not in params
        assert "deny_paths" not in params
        assert "denied_commands" not in params

    # load_skill is left untouched (no path/command partial).
    assert reg["load_skill"]["fn"] is tool_registry["load_skill"]["fn"]

    assert isinstance(reg["read_file"]["fn"], partial)
    # shell also gets the sticky-cwd wrapper (see TestCwdStickiness), so its
    # guard-bound partial is one layer deeper — checked functionally below
    # instead of by isinstance.
    assert reg["shell"]["fn"] is not tool_registry["shell"]["fn"]

    ok = reg["read_file"]["fn"](path=str(allowed / "f.txt"))
    assert ok["ok"] is True

    import pytest

    with pytest.raises(PermissionError):
        reg["read_file"]["fn"](path=str(secret))

    with pytest.raises(PermissionError, match="denied_commands"):
        reg["shell"]["fn"](command=["rm", "-rf", "x"], cwd=str(allowed))


class TestCwdStickiness:
    """set_cwd's whole point: shell/shell_readonly default to it once set,
    without the model repeating 'cwd' on every call — both immediately
    within the same registry build and, via .meta.json, across resumes."""

    def test_shell_defaults_to_process_cwd_when_never_set(self, tmp_path, monkeypatch):
        from scripts.amon.tools.registry import get_registry

        (tmp_path / "m.txt").write_text("x")
        monkeypatch.chdir(tmp_path)
        reg = get_registry(tools=["shell"], allowed_tools=["shell"])
        # No cwd passed and no set_cwd call yet — falls through to run_shell's
        # own default ("."), unchanged from before this feature existed.
        out = reg["shell"]["fn"](command=["ls"])
        assert "m.txt" in out

    def test_set_cwd_takes_immediate_effect_on_shell_in_the_same_registry(
        self, tmp_path
    ):
        from scripts.amon.tools.registry import get_registry

        (tmp_path / "m.txt").write_text("x")
        reg = get_registry(
            tools=["shell", "set_cwd"], allowed_tools=["shell", "set_cwd"]
        )
        reg["set_cwd"]["fn"](cwd=str(tmp_path))
        # No cwd argument this time — should use the sticky value just set.
        out = reg["shell"]["fn"](command=["ls"])
        assert "m.txt" in out

    def test_explicit_cwd_still_overrides_the_sticky_default(self, tmp_path):
        from scripts.amon.tools.registry import get_registry

        sticky_dir = tmp_path / "sticky"
        sticky_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "only-here.txt").write_text("x")

        reg = get_registry(
            tools=["shell", "set_cwd"], allowed_tools=["shell", "set_cwd"]
        )
        reg["set_cwd"]["fn"](cwd=str(sticky_dir))
        out = reg["shell"]["fn"](command=["ls"], cwd=str(other_dir))
        assert "only-here.txt" in out

    def test_a_rejected_set_cwd_call_does_not_change_the_sticky_default(self, tmp_path):
        from scripts.amon.tools.registry import get_registry

        (tmp_path / "m.txt").write_text("x")
        reg = get_registry(
            tools=["shell", "set_cwd"], allowed_tools=["shell", "set_cwd"]
        )
        import pytest

        with pytest.raises(NotADirectoryError):
            reg["set_cwd"]["fn"](cwd=str(tmp_path / "does-not-exist"))
        # Sticky default must still be untouched (".").
        out = reg["shell"]["fn"](command=["ls"], cwd=str(tmp_path))
        assert "m.txt" in out

    def test_set_cwd_calls_save_session_cwd_with_the_session_id(self, tmp_path):
        from uuid import uuid4

        from scripts.amon.tools.registry import get_registry

        session_id = uuid4()
        reg = get_registry(
            tools=["set_cwd"], allowed_tools=["set_cwd"], session_id=session_id
        )
        with patch("scripts.amon.tools.registry.save_session_cwd") as save:
            reg["set_cwd"]["fn"](cwd=str(tmp_path))
        save.assert_called_once_with(session_id, str(tmp_path))

    def test_a_recorded_session_cwd_seeds_the_next_registry_build(self, tmp_path):
        from uuid import uuid4

        from scripts.amon.tools.registry import get_registry

        (tmp_path / "resumed.txt").write_text("x")
        session_id = uuid4()
        with patch(
            "scripts.amon.tools.registry.load_session_cwd", return_value=str(tmp_path)
        ):
            reg = get_registry(
                tools=["shell"], allowed_tools=["shell"], session_id=session_id
            )
        out = reg["shell"]["fn"](command=["ls"])
        assert "resumed.txt" in out

    def test_no_session_id_skips_the_meta_json_lookup(self):
        from scripts.amon.tools.registry import get_registry

        with patch("scripts.amon.tools.registry.load_session_cwd") as load:
            get_registry(tools=["shell"], allowed_tools=["shell"], session_id=None)
        load.assert_not_called()

    def test_set_cwd_respects_agent_allow_paths(self, tmp_path):
        from scripts.amon.tools.registry import get_registry

        allowed = tmp_path / "ok"
        allowed.mkdir()
        outside = tmp_path / "nope"
        outside.mkdir()

        reg = get_registry(
            tools=["set_cwd"],
            allowed_tools=["set_cwd"],
            allow_paths=[str(allowed / "**")],
        )
        import pytest

        with pytest.raises(PermissionError, match="allow_paths"):
            reg["set_cwd"]["fn"](cwd=str(outside))


def test_run_task_forwards_path_guards_to_registry():
    agent = Agent(
        name="a",
        description="d",
        system_prompt="s",
        tools=["read_file"],
        allowed_tools=["read_file"],
        allow_paths=["/work/**"],
        deny_paths=["**/.env"],
        denied_commands=["sudo"],
    )

    with (
        patch("scripts.amon.tools.agent.run_agent") as run,
        patch("scripts.amon.tools.registry.get_registry") as gr,
    ):
        gr.return_value = {}
        run.return_value = AgentResult(ok=True, result="done")
        asyncio.run(agent.run_task("task"))

    kwargs = gr.call_args.kwargs
    assert kwargs["allow_paths"] == ["/work/**"]
    assert kwargs["deny_paths"] == ["**/.env"]
    assert kwargs["denied_commands"] == ["sudo"]


def test_headless_payload_single_and_multi():
    from scripts.amon.amon_cli import _headless_payload

    one = [{"ok": True, "agent": "a", "task": "t", "result": "r"}]
    assert _headless_payload(one) == one[0]

    multi = [
        {"ok": True, "agent": "a", "task": "t1", "result": "r1"},
        {"ok": False, "agent": "b", "task": "t2", "result": None},
    ]
    payload = _headless_payload(multi)
    assert payload["ok"] is False
    assert payload["results"] == multi


def test_run_jobs():
    from scripts.amon.tools.registry import READY_AGENTS

    seen = {}

    async def async_run_task(task: str, save_session: bool = True, **kwargs):
        seen["save_session"] = save_session
        seen["kwargs"] = kwargs
        return AgentResult(
            ok=True,
            result="result",
            error=None,
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            turns=1,
            tools_used=["shell"],
            session_id=None,
        )

    mock_agent = MagicMock()
    mock_agent.run_task = async_run_task
    with patch.dict(READY_AGENTS, {"test": mock_agent}, clear=True):
        jobs = [{"agent": "test", "task": "do something"}]
        results = asyncio.run(run_jobs(jobs))
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["ok"] is True
        assert results[0]["agent"] == "test"
        assert results[0]["task"] == "do something"
        assert results[0]["result"] == "result"
        assert results[0]["tools_used"] == ["shell"]
        # Default must be False (match CLI headless / docs).
        assert seen["save_session"] is False


def test_spawn_agents_save_session_opt_in():
    from scripts.amon.tools.registry import READY_AGENTS

    seen = {}

    async def async_run_task(task: str, save_session: bool = True, **kwargs):
        seen["save_session"] = save_session
        return AgentResult(ok=True, result="ok")

    mock_agent = MagicMock()
    mock_agent.run_task = async_run_task
    with patch.dict(READY_AGENTS, {"test": mock_agent}, clear=True):
        asyncio.run(run_jobs([{"agent": "test", "task": "t", "save_session": True}]))
        assert seen["save_session"] is True


def test_run_jobs_unknown_agent():
    from scripts.amon.tools.registry import READY_AGENTS

    with patch.dict(READY_AGENTS, {}, clear=True):
        results = asyncio.run(run_jobs([{"agent": "missing", "task": "x"}]))
        assert results[0]["ok"] is False
        assert results[0]["error"] == "Unknown agent: missing"
        assert results[0]["result"] is None


def test_usage_accumulates_across_turns():
    from scripts.amon.agent_loop import _add_usage, _empty_usage, _turn_usage

    a = _turn_usage({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
    b = _turn_usage({"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23})
    acc = _add_usage(_add_usage(_empty_usage(), a), b)
    assert acc == {
        "prompt_tokens": 30,
        "completion_tokens": 5,
        "total_tokens": 35,
    }


def test_print_headless_result_list_and_error(capsys):
    from scripts.amon import terminal

    terminal.print_headless_result(
        [
            {
                "ok": True,
                "agent": "default",
                "task": "list packages",
                "result": "Found 3 packages",
                "usage": {"total_tokens": 100},
                "turns": 2,
                "tools_used": ["shell_readonly"],
            },
            {
                "ok": False,
                "agent": "planner",
                "task": "plan",
                "result": None,
                "error": "Unknown agent: planner",
            },
        ]
    )
    out = capsys.readouterr().out
    assert "default" in out
    assert "list packages" in out
    assert "Found 3 packages" in out
    assert "tokens=100" in out
    assert "turns=2" in out
    assert "shell_readonly" in out
    assert "Unknown agent: planner" in out


def test_json_requires_headless():
    import argparse
    from scripts.amon.amon_cli import main

    with patch(
        "argparse.ArgumentParser.parse_args",
        return_value=argparse.Namespace(
            resume=False,
            resume_id=None,
            list_sessions=False,
            list_agents=False,
            delete_session=None,
            keep_N_sessions=None,
            headless=None,
            json=True,
            agent="default",
            save_session=False,
            session_id=None,
            model=None,
            max_turns=None,
            stream=False,
        ),
    ):
        # argparse.ArgumentParser.error raises SystemExit
        try:
            main()
            raised = False
        except SystemExit as e:
            raised = True
            assert e.code == 2
        assert raised, "--json without --headless should SystemExit(2)"


def test_spawn_agents_tool_returns_json_string():
    from scripts.amon.tools.registry import _spawn_agents

    payload = json.dumps({"ok": True, "result": "hi", "error": None}).encode()

    class _FakeStream:
        def __init__(self, data: bytes):
            self._data = data

        async def read(self):
            return self._data

        async def readline(self):
            return b""

    class FakeProc:
        def __init__(self):
            self.stdout = _FakeStream(payload)
            self.stderr = _FakeStream(b"")

        async def wait(self):
            return 0

    async def fake_exec(*cmd, **kwargs):
        return FakeProc()

    with patch("asyncio.create_subprocess_exec", fake_exec):
        raw = _spawn_agents(jobs=[{"agent": "test", "task": "t"}])
    assert isinstance(raw, str)
    data = json.loads(raw)
    assert data[0]["ok"] is True
    assert data[0]["result"] == "hi"


def test_spawn_agents_tool_schema_documents_save_session():
    from scripts.amon.tools.registry import tool_registry

    schema = tool_registry["spawn_agents"]["schema"]["function"]
    props = schema["parameters"]["properties"]["jobs"]["items"]["properties"]
    assert "save_session" in props
    assert "session_id" in props
    assert "model" in props
    assert "max_turns" in props
    assert "output" in schema["parameters"]["properties"]
    assert "JSON" in schema["description"] or "json" in schema["description"].lower()
    assert "ok" in schema["description"]


def test_run_task_resolves_model_and_max_turns_overrides():
    from scripts.amon.tools.agent import Agent

    agent = Agent(
        name="t",
        description="d",
        system_prompt="s",
        tools=["shell"],
        allowed_tools=["shell"],
        model="agent-model",
        max_turns=9,
    )
    with patch("scripts.amon.tools.agent.run_agent") as run:
        run.return_value = AgentResult(ok=True, result="ok")
        asyncio.run(agent.run_task("task", model="job-model", max_turns=3))
    kwargs = run.call_args.kwargs
    assert kwargs["model"] == "job-model"
    assert kwargs["max_turns"] == 3

    with patch("scripts.amon.tools.agent.run_agent") as run:
        run.return_value = AgentResult(ok=True, result="ok")
        asyncio.run(agent.run_task("task"))
    kwargs = run.call_args.kwargs
    assert kwargs["model"] == "agent-model"
    assert kwargs["max_turns"] == 9


def test_run_jobs_forwards_session_model_max_turns():
    from scripts.amon.tools.registry import READY_AGENTS

    seen = {}

    async def async_run_task(task: str, save_session: bool = True, **kwargs):
        seen.update(kwargs)
        seen["save_session"] = save_session
        return AgentResult(ok=True, result="ok")

    mock_agent = MagicMock()
    mock_agent.run_task = async_run_task
    with patch.dict(READY_AGENTS, {"test": mock_agent}, clear=True):
        asyncio.run(
            run_jobs(
                [
                    {
                        "agent": "test",
                        "task": "t",
                        "session_id": "sid-1",
                        "model": "m1",
                        "max_turns": 7,
                    }
                ]
            )
        )
    assert seen["session_id"] == "sid-1"
    assert seen["model"] == "m1"
    assert seen["max_turns"] == 7
