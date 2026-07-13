import json
import asyncio
from pathlib import Path
from scripts.amon.agent_loop import run_agent
from scripts.amon.tools.registry import get_registry
from config import AGENTS_DIR
from pydantic import BaseModel, Field
from typing import Any, Literal

from scripts.amon.tools.skills import catalog_for_agent


class Agent(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str] | dict[str, Any]
    allowed_tools: list[str]
    max_turns: int = Field(gt=0)
    allowed_skills: list[str]

    @classmethod
    def from_file(cls, config_path: Path) -> "Agent":
        with open(config_path) as f:
            config = json.load(f)
        return cls(**config)

    async def run_task(self, task: str, save_session: bool = True) -> str:
        return await asyncio.to_thread(
            run_agent,
            system_prompt=self.system_prompt,
            user_input=task,
            tool_registry=get_registry(
                tools=self.tools, allowed_tools=self.allowed_tools
            ),
            skill_catalog=catalog_for_agent(self.allowed_skills)
            headless=True,
            save_session_=save_session,
            max_turns=self.max_turns,
        )


def load_ready_agents() -> dict[str, Agent]:
    return {f.stem: Agent.from_file(f) for f in AGENTS_DIR.glob("*.json")}


READY_AGENTS = load_ready_agents()
AgentName = Literal.__getitem__(tuple(READY_AGENTS.keys()))


async def spawn_agents(jobs: list[dict]) -> dict[str, str]:

    async def run_one(job):
        agent = READY_AGENTS[job["agent"]]
        result = await agent.run_task(task=job["task"])
        return job["agent"] + ":" + job["task"], result

    results = await asyncio.gather(*[run_one(j) for j in jobs])
    return dict(results)
