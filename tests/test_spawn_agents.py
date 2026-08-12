"""Tests for spawn_agents: child processes, concurrency cap, timeout kill."""

import asyncio
import json
from unittest.mock import patch

from scripts.amon.tools.agent import spawn_agents

PAYLOAD = {
    "ok": True,
    "result": "done",
    "error": None,
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    "turns": 1,
    "tools_used": ["shell"],
    "session_id": None,
}


class FakeProc:
    """Stands in for an asyncio subprocess."""

    def __init__(self, stdout=b"", stderr=b"", delay=0.0):
        self._stdout, self._stderr, self._delay = stdout, stderr, delay
        self.killed = False

    async def communicate(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


def _exec_patch(proc, calls=None, live=None):
    async def fake_exec(*cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        if live is not None:
            live["now"] = live.get("now", 0) + 1
            live["peak"] = max(live.get("peak", 0), live["now"])
        return proc() if callable(proc) else proc

    return patch("asyncio.create_subprocess_exec", fake_exec)


def test_successful_child_payload_is_returned():
    proc = FakeProc(stdout=json.dumps(PAYLOAD).encode())
    with _exec_patch(proc):
        results = asyncio.run(spawn_agents([{"agent": "worker", "task": "do it"}]))
    assert results[0]["ok"] is True
    assert results[0]["result"] == "done"
    assert results[0]["agent"] == "worker"
    assert results[0]["task"] == "do it"


def test_command_targets_headless_json_run():
    calls = []
    proc = FakeProc(stdout=json.dumps(PAYLOAD).encode())
    with _exec_patch(proc, calls=calls):
        asyncio.run(spawn_agents([{"agent": "worker", "task": "do it"}]))
    cmd = calls[0]
    assert "scripts.amon.amon_cli" in cmd
    assert "--headless" in cmd and "do it" in cmd
    assert "--agent" in cmd and "worker" in cmd
    assert "--json" in cmd
    assert "--save-session" not in cmd


def test_save_session_is_forwarded():
    calls = []
    proc = FakeProc(stdout=json.dumps(PAYLOAD).encode())
    with _exec_patch(proc, calls=calls):
        asyncio.run(spawn_agents([{"agent": "w", "task": "t", "save_session": True}]))
    assert "--save-session" in calls[0]


def test_non_json_output_reports_stderr():
    proc = FakeProc(stdout=b"not json", stderr=b"child blew up")
    with _exec_patch(proc):
        results = asyncio.run(spawn_agents([{"agent": "w", "task": "t"}]))
    assert results[0]["ok"] is False
    assert "child blew up" in results[0]["error"]


def test_timeout_kills_the_child():
    proc = FakeProc(stdout=json.dumps(PAYLOAD).encode(), delay=5)
    with _exec_patch(proc):
        results = asyncio.run(
            spawn_agents([{"agent": "w", "task": "t"}], timeout_s=0.05)
        )
    assert results[0]["ok"] is False
    assert "timed out" in results[0]["error"]
    assert proc.killed is True


def test_max_parallel_caps_concurrent_children():
    live = {}

    def make():
        async def release(_p=None):
            live["now"] -= 1
            return json.dumps(PAYLOAD).encode(), b""

        proc = FakeProc(stdout=json.dumps(PAYLOAD).encode(), delay=0.02)
        original = proc.communicate

        async def communicate():
            out = await original()
            live["now"] -= 1
            return out

        proc.communicate = communicate
        return proc

    jobs = [{"agent": "w", "task": f"t{i}"} for i in range(6)]
    with _exec_patch(make, live=live):
        results = asyncio.run(spawn_agents(jobs, max_parallel=2))
    assert len(results) == 6
    assert live["peak"] <= 2


def test_all_jobs_are_reported():
    proc = FakeProc(stdout=json.dumps(PAYLOAD).encode())
    jobs = [{"agent": "w", "task": f"t{i}"} for i in range(3)]
    with _exec_patch(proc):
        results = asyncio.run(spawn_agents(jobs))
    assert [r["task"] for r in results] == ["t0", "t1", "t2"]
