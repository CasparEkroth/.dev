import json
import asyncio
import logging
from pathlib import Path
from config import DEFAULT_MAX_TURNS
from scripts.amon.agent_loop import AgentResult, run_agent
from pydantic import BaseModel, Field, ValidationError, model_validator
from typing import Any
from scripts.amon.tools.skills import catalog_for_agent

logger = logging.getLogger(__name__)


class Agent(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str]
    allowed_tools: list[str]
    max_turns: int = Field(default=DEFAULT_MAX_TURNS, gt=0)
    allowed_skills: list[str] = Field(default_factory=list)
    hooks: dict[str, str] = Field(default_factory=dict)
    #: Require a tool call on the first turn. Off by default so an agent can
    #: open with a clarifying question.
    force_first_tool: bool = False
    #: Wall-clock budget for one run, in seconds. None = no limit.
    max_runtime_s: float | None = None
    #: Model id for this agent; falls back to the configured default.
    model: str | None = None
    #: STUB — accepted and validated, but NOT connected yet. Mirrors the usual
    #: server config shapes (local: command/args/env/timeout/disabled/
    #: disabledTools; remote: url/headers/oauth/oauthScopes) so configs written
    #: now keep working once MCP support lands.
    #: TODO: spin up the declared servers and register their tools.
    mcp_servers: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def expand_wildcards(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("tools") in (["*"], "*") or data.get("allowed_tools") in (
                ["*"],
                "*",
            ):
                from scripts.amon.tools.registry import tool_registry

                if data.get("tools") in (["*"], "*"):
                    data["tools"] = list(tool_registry.keys())
                if data.get("allowed_tools") in (["*"], "*"):
                    data["allowed_tools"] = list(tool_registry.keys())
        return data

    @classmethod
    def from_file(cls, config_path: Path) -> "Agent":
        if not config_path.exists():
            raise FileNotFoundError(f"Agent config not found: {config_path}")
        try:
            with open(config_path) as f:
                return cls.model_validate_json(f.read())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {config_path}: {e}") from e
        except ValidationError as e:
            raise ValueError(f"Invalid agent config in {config_path}: {e}") from e

    async def run_task(self, task: str, save_session: bool = True) -> AgentResult:
        from scripts.amon.tools.registry import get_registry

        return await asyncio.to_thread(
            run_agent,
            system_prompt=self.system_prompt,
            user_input=task,
            tool_registry=get_registry(
                tools=self.tools, allowed_tools=self.allowed_tools
            ),
            skill_catalog=catalog_for_agent(self.allowed_skills),
            headless=True,
            save_session_=save_session,
            max_turns=self.max_turns,
            hooks=self.hooks,
            force_first_tool=self.force_first_tool,
            max_runtime_s=self.max_runtime_s,
            model=self.model,
        )


def load_ready_agents() -> dict[str, Agent]:
    agents: dict[str, Agent] = {}

    system_path = Path("/etc/.amon/agents")
    home_path = Path.home() / ".amon/agents"
    cwd_path = Path.cwd() / ".amon/agents"

    for path in (system_path, home_path, cwd_path):
        if path.is_dir():
            for f in path.glob("*.json"):
                try:
                    agents[f.stem] = Agent.from_file(f)
                except Exception as exc:  # FileNotFound, JSON, Validation, etc.
                    logger.warning("Skipping agent %s: %s", f.name, exc)
    return agents


async def spawn_agents(jobs: list[dict]) -> list[dict]:
    """Run agent jobs concurrently and return structured result dicts."""
    from scripts.amon.tools.registry import READY_AGENTS

    async def run_one(job: dict) -> dict:
        agent_name = job.get("agent", "")
        task = job.get("task", "")
        try:
            if agent_name not in READY_AGENTS:
                return {
                    "ok": False,
                    "agent": agent_name,
                    "task": task,
                    "result": None,
                    "error": f"Unknown agent: {agent_name}",
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "turns": 0,
                    "tools_used": [],
                    "session_id": None,
                }
            agent = READY_AGENTS[agent_name]
            # Default False: match CLI headless (opt-in via --save-session / job flag).
            result = await agent.run_task(
                task=task, save_session=bool(job.get("save_session", False))
            )
            payload = (
                result.to_dict()
                if isinstance(result, AgentResult)
                else {
                    "ok": True,
                    "result": result,
                    "error": None,
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "turns": 0,
                    "tools_used": [],
                    "session_id": None,
                }
            )
            payload["agent"] = agent_name
            payload["task"] = task
            return payload
        except Exception as e:
            logger.exception("spawn_agents job failed for %s", agent_name)
            return {
                "ok": False,
                "agent": agent_name,
                "task": task,
                "result": None,
                "error": str(e),
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "turns": 0,
                "tools_used": [],
                "session_id": None,
            }

    return list(await asyncio.gather(*[run_one(j) for j in jobs]))
