import asyncio
import json
from unittest.mock import patch, MagicMock

from scripts.amon.agent_loop import AgentResult
from scripts.amon.tools.agent import (
    Agent,
    load_ready_agents,
    spawn_agents,
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
    # mcp_servers is a stub: accepted on the config, not yet wired into a run.
    assert "mcp_servers" not in kwargs


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

    entry = get_registry(tools=["shell"], allowed_tools=["shell"])["shell"]
    assert entry["fn"] is tool_registry["shell"]["fn"]
    assert entry["schema"] is tool_registry["shell"]["schema"]


def test_get_registry_selection_rules():
    from scripts.amon.tools.registry import get_registry

    assert get_registry() == {}
    assert get_registry(tools=["not_a_tool"]) == {}
    # No allowed_tools means everything needs confirmation.
    every = get_registry(tools=["shell", "read_file"])
    assert set(every) == {"shell", "read_file"}
    assert all(v["requires_confirmation"] for v in every.values())


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


def test_spawn_agents():
    from scripts.amon.tools.registry import READY_AGENTS

    seen = {}

    async def async_run_task(task: str, save_session: bool = True):
        seen["save_session"] = save_session
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
        results = asyncio.run(spawn_agents(jobs))
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

    async def async_run_task(task: str, save_session: bool = True):
        seen["save_session"] = save_session
        return AgentResult(ok=True, result="ok")

    mock_agent = MagicMock()
    mock_agent.run_task = async_run_task
    with patch.dict(READY_AGENTS, {"test": mock_agent}, clear=True):
        asyncio.run(
            spawn_agents([{"agent": "test", "task": "t", "save_session": True}])
        )
        assert seen["save_session"] is True


def test_spawn_agents_unknown_agent():
    from scripts.amon.tools.registry import READY_AGENTS

    with patch.dict(READY_AGENTS, {}, clear=True):
        results = asyncio.run(spawn_agents([{"agent": "missing", "task": "x"}]))
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
            delete_session=None,
            keep_N_sessions=None,
            headless=None,
            json=True,
            agent="default",
            save_session=False,
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
    from scripts.amon.tools.registry import READY_AGENTS, _spawn_agents

    async def async_run_task(task: str, save_session: bool = False):
        return AgentResult(ok=True, result="hi", tools_used=[])

    mock_agent = MagicMock()
    mock_agent.run_task = async_run_task
    with patch.dict(READY_AGENTS, {"test": mock_agent}, clear=True):
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
    assert "JSON" in schema["description"] or "json" in schema["description"].lower()
    assert "ok" in schema["description"]
