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

    async def async_run_task(task: str, save_session: bool = True):
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


def test_spawn_agents_unknown_agent():
    from scripts.amon.tools.registry import READY_AGENTS

    with patch.dict(READY_AGENTS, {}, clear=True):
        results = asyncio.run(spawn_agents([{"agent": "missing", "task": "x"}]))
        assert results[0]["ok"] is False
        assert results[0]["error"] == "Unknown agent: missing"
        assert results[0]["result"] is None
