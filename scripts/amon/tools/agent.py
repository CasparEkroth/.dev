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
    #: Per-agent ceiling for tool results; None keeps the global default.
    max_tool_output_chars: int | None = None
    #: TODO: accepted and validated, but no server is started yet.
    mcp_servers: dict[str, dict] = Field(default_factory=dict)
    #: Glob patterns of paths tools may touch. Empty = unrestricted (unless denied).
    allow_paths: list[str] = Field(default_factory=list)
    #: Glob patterns of paths tools must not touch. Deny always wins over allow.
    deny_paths: list[str] = Field(default_factory=list)
    #: Literal command names blocked for shell / shell_readonly (command position).
    denied_commands: list[str] = Field(default_factory=list)

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
    def normalize_wildcards(cls, data: Any) -> Any:
        """Accept a bare "*" as shorthand for ["*"].

        Does NOT expand to the full tool list here: at load time
        `tool_registry` doesn't have `spawn_agents` yet (it's added after
        `READY_AGENTS` loads, since its schema needs `READY_AGENTS`), so an
        agent validated at this point would silently lose it. Expansion
        happens in `get_registry` instead, which only ever runs after the
        registry is fully built.
        """
        if isinstance(data, dict):
            if data.get("tools") == "*":
                data["tools"] = ["*"]
            if data.get("allowed_tools") == "*":
                data["allowed_tools"] = ["*"]
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

    async def run_task(
        self,
        task: str,
        save_session: bool = True,
        session_id=None,
        model: str | None = None,
        max_turns: int | None = None,
    ) -> AgentResult:
        from scripts.amon.tools.registry import get_registry

        stream_actions = None
        if os.environ.get("AMON_STREAM"):
            from scripts.amon.terminal import stream_action_stderr

            stream_actions = stream_action_stderr

        event_log = None
        if os.environ.get("AMON_EVENTS"):
            from scripts.amon.agent_loop import file_event_log

            event_log = file_event_log

        return await asyncio.to_thread(
            run_agent,
            system_prompt=self.system_prompt,
            user_input=task,
            tool_registry=get_registry(
                tools=self.tools,
                allowed_tools=self.allowed_tools,
                allow_paths=self.allow_paths,
                deny_paths=self.deny_paths,
                denied_commands=self.denied_commands,
                session_id=session_id,
            ),
            skill_catalog=catalog_for_agent(self.allowed_skills),
            headless=True,
            save_session_=save_session,
            session_id=session_id,
            max_turns=max_turns or self.max_turns,
            hooks=self.hooks,
            force_first_tool=self.force_first_tool,
            max_runtime_s=self.max_runtime_s,
            model=model or self.model,
            system_prompt_template=self.system_prompt_template,
            stream_actions=stream_actions,
            max_tool_output_chars=self.max_tool_output_chars,
            agent_name=self.name,
            event_log=event_log,
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
                    agent = Agent.from_file(f)
                except Exception as exc:  # FileNotFound, JSON, Validation, etc.
                    logger.warning("Skipping agent %s: %s", f.name, exc)
                    continue
                if agent.name != f.stem:
                    logger.warning(
                        "Agent file %s has name %r but is keyed as %r "
                        "(--agent %r / spawn_agents will use the filename stem)",
                        f.name,
                        agent.name,
                        f.stem,
                        f.stem,
                    )
                agents[f.stem] = agent
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
                task=task,
                save_session=bool(job.get("save_session", False)),
                session_id=job.get("session_id"),
                model=job.get("model"),
                max_turns=job.get("max_turns"),
            )
            return {**result.to_dict(), "agent": agent_name, "task": task}
        except Exception as e:
            logger.exception("job failed for %s", agent_name)
            return _failed(agent_name, task, str(e))

    return list(await asyncio.gather(*[run_one(j) for j in jobs]))


async def _drain_stderr(stream: asyncio.StreamReader, agent_name: str) -> bytes:
    """Read a child's stderr line by line, forwarding it live when
    AMON_STREAM is set (inherited from the parent's env — see spawn_agents'
    `env`), while still returning the full bytes for the JSON-parse-failure
    fallback path. Previously this only ever showed up in that one fallback
    case; every other run silently discarded it until the whole batch
    finished.
    """
    stream_live = bool(os.environ.get("AMON_STREAM"))
    chunks: list[bytes] = []
    while True:
        line = await stream.readline()
        if not line:
            break
        chunks.append(line)
        if stream_live:
            from scripts.amon.terminal import stream_action_stderr

            stream_action_stderr(
                "child_stderr",
                {"agent": agent_name, "line": line.decode(errors="replace").rstrip()},
            )
    return b"".join(chunks)


async def spawn_agents(
    jobs: list[dict],
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    timeout_s: float | None = None,
    output: str | None = None,
) -> list[dict]:
    """Run agent jobs as child processes, at most *max_parallel* at a time.

    Children are separate processes, so one cannot corrupt shared state or
    outlive the parent: a job past *timeout_s* is killed. Each child is an
    `amon --headless --json` run and returns that payload.

    When *output* is set, the full result list is written there even if some
    jobs failed — that file is the outer harness checkpoint.
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
        if job.get("session_id"):
            cmd.extend(["--session-id", str(job["session_id"])])
        if job.get("model"):
            cmd.extend(["--model", str(job["model"])])
        if job.get("max_turns") is not None:
            cmd.extend(["--max-turns", str(job["max_turns"])])

        async with sem:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                out, err = await asyncio.wait_for(
                    asyncio.gather(
                        proc.stdout.read(),
                        _drain_stderr(proc.stderr, agent_name),
                    ),
                    timeout_s,
                )
                await proc.wait()
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return _failed(agent_name, task, f"timed out after {timeout_s}s")

        try:
            payload = json.loads(out)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _failed(agent_name, task, (err.decode() or "no output")[-500:])
        return {**payload, "agent": agent_name, "task": task}

    results = list(await asyncio.gather(*[run_one(j) for j in jobs]))
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return results
