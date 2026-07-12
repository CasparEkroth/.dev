import json
from unittest.mock import patch, MagicMock
import pytest

from scripts.amon.tools.agent import (
    Agent,
    load_ready_agents,
    spawn_agents,
    READY_AGENTS,
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


def test_load_ready_agents(monkeypatch):
    mock_dir = MagicMock()
    mock_file = MagicMock()
    mock_file.stem = "mock_agent"
    mock_dir.glob.return_value = [mock_file]

    with patch("scripts.agent.tools.agent.AGENTS_DIR", mock_dir):
        with patch.object(Agent, "from_file", return_value=MagicMock()):
            agents = load_ready_agents()
            assert "mock_agent" in agents


@pytest.mark.asyncio
async def test_spawn_agents():
    mock_agent = MagicMock()
    mock_agent.run_task.return_value = "result"
    with patch.dict(READY_AGENTS, {"test": mock_agent}, clear=True):
        jobs = [{"agent": "test", "task": "do something"}]
        results = await spawn_agents(jobs)
        assert "test:do something" in results
