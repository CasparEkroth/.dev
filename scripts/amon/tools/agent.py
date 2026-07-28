import json
import asyncio
import logging
from pathlib import Path
from scripts.amon.agent_loop import run_agent
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
    max_turns: int = Field(default=10, gt=0)
    allowed_skills: list[str] = Field(default_factory=list)
    hooks: dict[str, str] = Field(default_factory=dict)

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

    async def run_task(self, task: str, save_session: bool = True) -> str:
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


async def spawn_agents(jobs: list[dict]) -> dict[str, str]:
    from scripts.amon.tools.registry import READY_AGENTS

    async def run_one(job):
        agent = READY_AGENTS[job["agent"]]
        result = await agent.run_task(task=job["task"])
        return job["agent"] + ":" + job["task"], result

    results = await asyncio.gather(*[run_one(j) for j in jobs])
    return dict(results)
