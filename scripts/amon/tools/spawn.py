"""In-process job runner and child-process spawn_agents implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from config import DEFAULT_MAX_PARALLEL, REPO_DIR

logger = logging.getLogger(__name__)


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
        from scripts.amon.memory import agent_mismatch_warning

        agent_name = job.get("agent", "")
        task = job.get("task", "")
        try:
            if agent_name not in READY_AGENTS:
                return _failed(agent_name, task, f"Unknown agent: {agent_name}")
            warning = None
            if job.get("session_id") is not None:
                warning = agent_mismatch_warning(job["session_id"], agent_name)
                if warning:
                    print(warning, file=sys.stderr)
            # Default False: match CLI headless (opt-in via --save-session / job flag).
            result = await READY_AGENTS[agent_name].run_task(
                task=task,
                save_session=bool(job.get("save_session", False)),
                session_id=job.get("session_id"),
                model=job.get("model"),
                max_turns=job.get("max_turns"),
            )
            return {
                **result.to_dict(),
                "agent": agent_name,
                "task": task,
                "agent_warning": warning,
            }
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
