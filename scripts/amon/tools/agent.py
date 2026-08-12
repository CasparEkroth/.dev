import json
import asyncio
import logging
import os
import sys
from pathlib import Path
from config import DEFAULT_MAX_PARALLEL, DEFAULT_MAX_TURNS, REPO_DIR
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
    #: event -> [{command, matcher?, timeout_ms?}]. A bare string or a list of
    #: strings is accepted and normalized to this form.
    hooks: dict[str, list[dict]] = Field(default_factory=dict)
    #: Require a tool call on turn 0. Off so an agent can open with a question.
    force_first_tool: bool = False
    #: Wall-clock budget for one run, in seconds.
    max_runtime_s: float | None = None
    model: str | None = None
    #: See DEFAULT_SYSTEM_PROMPT_TEMPLATE.
    system_prompt_template: str | None = None
    #: TODO: accepted and validated, but no server is started yet.
    mcp_servers: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_hooks(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("hooks"), dict):
            data["hooks"] = {
                event: [
                    {"command": s} if isinstance(s, str) else s
                    for s in ([spec] if isinstance(spec, (str, dict)) else spec)
                ]
                for event, spec in data["hooks"].items()
            }
        return data

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
            system_prompt_template=self.system_prompt_template,
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


def _failed(agent: str, task: str, error: str) -> dict:
    """Result payload for a job that never produced one."""
    return {
        "ok": False,
        "agent": agent,
        "task": task,
        "result": None,
        "error": error,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "turns": 0,
        "tools_used": [],
        "session_id": None,
    }


async def run_jobs(jobs: list[dict]) -> list[dict]:
    """Run agent jobs in THIS process. Used by `amon --headless`."""
    from scripts.amon.tools.registry import READY_AGENTS

    async def run_one(job: dict) -> dict:
        agent_name = job.get("agent", "")
        task = job.get("task", "")
        try:
            if agent_name not in READY_AGENTS:
                return _failed(agent_name, task, f"Unknown agent: {agent_name}")
            # Default False: match CLI headless (opt-in via --save-session / job flag).
            result = await READY_AGENTS[agent_name].run_task(
                task=task, save_session=bool(job.get("save_session", False))
            )
            return {**result.to_dict(), "agent": agent_name, "task": task}
        except Exception as e:
            logger.exception("job failed for %s", agent_name)
            return _failed(agent_name, task, str(e))

    return list(await asyncio.gather(*[run_one(j) for j in jobs]))


async def spawn_agents(
    jobs: list[dict],
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    timeout_s: float | None = None,
) -> list[dict]:
    """Run agent jobs as child processes, at most *max_parallel* at a time.

    Children are separate processes, so one cannot corrupt shared state or
    outlive the parent: a job past *timeout_s* is killed. Each child is an
    `amon --headless --json` run and returns that payload.
    """
    sem = asyncio.Semaphore(max(1, max_parallel))
    # The child is launched as a module, so it needs the repo on PYTHONPATH; cwd
    # is inherited because it defines the agent's workspace.
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            p for p in (str(REPO_DIR), os.environ.get("PYTHONPATH", "")) if p
        ),
    }

    async def run_one(job: dict) -> dict:
        agent_name = job.get("agent", "")
        task = job.get("task", "")
        cmd = [
            sys.executable,
            "-m",
            "scripts.amon.amon_cli",
            "--headless",
            task,
            "--agent",
            agent_name,
            "--json",
        ]
        if job.get("save_session"):
            cmd.append("--save-session")

        async with sem:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return _failed(agent_name, task, f"timed out after {timeout_s}s")

        try:
            payload = json.loads(out)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _failed(agent_name, task, (err.decode() or "no output")[-500:])
        return {**payload, "agent": agent_name, "task": task}

    return list(await asyncio.gather(*[run_one(j) for j in jobs]))
