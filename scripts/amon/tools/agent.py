"""Agent model, config loading, and task execution.

Job orchestration (`run_jobs`, `spawn_agents`) lives in ``scripts.amon.tools.spawn``
and is re-exported here for stable import paths.
"""

from __future__ import annotations

import json
import asyncio
import logging
import os
from pathlib import Path
from config import (
    AMON_CONFIG_ROOT,
    DEFAULT_MAX_TURNS,
)
from scripts.amon.agent_loop import AgentResult, run_agent
from pydantic import BaseModel, Field, ValidationError, model_validator
from typing import Any
from scripts.amon.tools.skills import catalog_for_agent
from scripts.amon.tools.spawn import (  # noqa: F401 — re-export
    run_jobs,
    spawn_agents,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Agent",
    "load_ready_agents",
    "run_jobs",
    "spawn_agents",
]


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
    #: server_name -> {command, args, env, timeout, disabled, disabledTools}
    #: (stdio) or {url, headers, timeout, disabled, disabledTools} (remote).
    #: Discovered and merged into the tool registry per run — see
    #: scripts/amon/tools/mcp.py:discover_mcp_tools.
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

        mcp_tools = None
        mcp_closers: list = []
        if self.mcp_servers:
            from scripts.amon.tools.mcp import discover_mcp_tools

            mcp_tools, mcp_closers = await discover_mcp_tools(self.mcp_servers)

        try:
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
                    extra_tools=mcp_tools,
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
        finally:
            for closer in mcp_closers:
                closer()


def load_ready_agents() -> dict[str, Agent]:
    agents: dict[str, Agent] = {}

    if AMON_CONFIG_ROOT:
        # Hermetic: only the explicit root — skip system/home/cwd merge.
        roots = (Path(AMON_CONFIG_ROOT) / "agents",)
    else:
        system_path = Path("/etc/.amon/agents")
        home_path = Path.home() / ".amon/agents"
        cwd_path = Path.cwd() / ".amon/agents"
        roots = (system_path, home_path, cwd_path)

    for path in roots:
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
