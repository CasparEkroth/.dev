from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID
import os
import json

from scripts.amon.hooks import HookEventName, run_hook_event
from scripts.amon.memory import save_context_tokens, save_session, load_session
from shared.llm_client import call_llm_with_tools


@dataclass
class AgentResult:
    """Structured result returned by run_agent."""

    ok: bool
    result: str | None
    error: str | None = None
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )
    turns: int = 0
    tools_used: list[str] = field(default_factory=list)
    session_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "usage": dict(self.usage),
            "turns": self.turns,
            "tools_used": list(self.tools_used),
            "session_id": self.session_id,
        }


def _empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _turn_usage(raw: dict | None) -> dict[str, int]:
    """Normalize one LLM response usage blob."""
    raw = raw or {}
    prompt = int(raw.get("prompt_tokens") or 0)
    completion = int(raw.get("completion_tokens") or 0)
    total = int(raw.get("total_tokens") or (prompt + completion) or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _add_usage(acc: dict[str, int], turn: dict[str, int]) -> dict[str, int]:
    """Accumulate usage across turns (full-run totals)."""
    return {
        "prompt_tokens": acc["prompt_tokens"] + turn["prompt_tokens"],
        "completion_tokens": acc["completion_tokens"] + turn["completion_tokens"],
        "total_tokens": acc["total_tokens"] + turn["total_tokens"],
    }


def run_agent(
    system_prompt: str,
    user_input: str,
    tool_registry: dict,
    skill_catalog: dict,
    max_turns: int = 30,
    confirm_fn=None,
    stream_actions=None,
    token_fn=None,
    session_id: UUID = None,
    save_session_: bool = True,
    headless: bool = False,
    hooks: dict[str, str] = {},
) -> AgentResult:
    """
    tool_registry: {"send_email": {"schema": {...}, "fn": callable}, ...}
    """
    from scripts.amon.terminal import confirm_tool, stream_action

    tool_definitions = [t["schema"] for t in tool_registry.values()]
    confirm_fn = confirm_fn or confirm_tool
    stream_actions = stream_actions or stream_action if not headless else None
    token_fn = token_fn if not headless else None

    system_prompt = build_system_prompt(system_prompt, skill_catalog)
    history = load_session(session_id) if session_id else []
    conversation = history + [{"role": "user", "content": user_input}]
    new_messages = [{"role": "user", "content": user_input}]

    tools_used: list[str] = []
    # last_usage = latest turn (context window size for footer/persist).
    # accumulated_usage = sum across turns (what AgentResult.usage reports).
    last_usage = _empty_usage()
    accumulated_usage = _empty_usage()
    last_content = ""
    active_session_id = session_id

    def _persist(usage_dict: dict) -> None:
        nonlocal active_session_id
        if not save_session_:
            return
        active_session_id = save_session(new_messages, session_id=active_session_id)
        if active_session_id:
            # Context size is the latest prompt window, not the run sum.
            save_context_tokens(active_session_id, usage_dict.get("prompt_tokens", 0))

    def _finish(
        *,
        ok: bool,
        result: str | None,
        error: str | None,
        turns: int,
    ) -> AgentResult:
        sid = str(active_session_id) if active_session_id else None
        return AgentResult(
            ok=ok,
            result=result,
            error=error,
            usage=dict(accumulated_usage),
            turns=turns,
            tools_used=list(tools_used),
            session_id=sid,
        )

    if hooks.get(HookEventName.START):
        run_hook_event(
            path=hooks.get(HookEventName.START),
            session_id=active_session_id,
            hook_event_name=HookEventName.START,
            cwd=os.getcwd(),
            prompt=user_input,
        )

    message = {"content": ""}
    for turn in range(max_turns):
        response = call_llm_with_tools(
            system_prompt,
            conversation,
            tool_definitions,
            force_tool=turn == 0 and bool(tool_definitions),
        )

        # Extract the message from the full ChatCompletionResponse
        choice = response["choices"][0]
        message = choice["message"]
        last_usage = _turn_usage(response.get("usage"))
        accumulated_usage = _add_usage(accumulated_usage, last_usage)
        last_content = message.get("content") or last_content

        conversation.append(message)
        new_messages.append(message)

        if message.get("content") and stream_actions:
            stream_actions("reasoning", {"content": message["content"]})

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            _persist(last_usage)

            if hooks.get(HookEventName.STOP):
                run_hook_event(
                    path=hooks.get(HookEventName.STOP),
                    session_id=active_session_id,
                    hook_event_name=HookEventName.STOP,
                    cwd=os.getcwd(),
                    response=message.get("content", ""),
                )
            return _finish(
                ok=True,
                result=message.get("content") or "",
                error=None,
                turns=turn + 1,
            )

        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            tools_used.append(name)

            fn = tool_registry[name]["fn"]
            need_confirmation = tool_registry[name]["requires_confirmation"]
            if headless and need_confirmation:
                result = (
                    f"Agent is running in headless mode and doesn't have "
                    f"permission to run tool {name}."
                )
            elif need_confirmation and not confirm_fn(name, args):
                result = (
                    f"User denied permission to run tool '{name}' with args {args}."
                )
            else:
                try:
                    if hooks.get(HookEventName.PRE_TOOL_USE):
                        run_hook_event(
                            path=hooks.get(HookEventName.PRE_TOOL_USE),
                            session_id=active_session_id,
                            hook_event_name=HookEventName.PRE_TOOL_USE,
                            cwd=os.getcwd(),
                            tool_name=name,
                            tool_input=args,
                        )

                    if stream_actions:
                        stream_actions("tool_call", {"name": name, "args": args})
                    result = fn(**args)
                except Exception as e:
                    _persist(last_usage)
                    result = f"Error: {e}"
            tool_msg = {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": str(result),
            }

            if hooks.get(HookEventName.POST_TOOL_USE):
                run_hook_event(
                    path=hooks.get(HookEventName.POST_TOOL_USE),
                    session_id=active_session_id,
                    hook_event_name=HookEventName.POST_TOOL_USE,
                    cwd=os.getcwd(),
                    tool_name=name,
                    tool_input=args,
                    tool_output=str(result),
                )

            if stream_actions:
                stream_actions("tool_result", {"name": name, "content": str(result)})
            conversation.append(tool_msg)
            new_messages.append(tool_msg)

        if token_fn:
            token_fn(
                tokens_added=last_usage["total_tokens"],
                context=last_usage["prompt_tokens"],
            )

    _persist(last_usage)

    if hooks.get(HookEventName.STOP):
        run_hook_event(
            path=hooks.get(HookEventName.STOP),
            session_id=active_session_id,
            hook_event_name=HookEventName.STOP,
            cwd=os.getcwd(),
            response=message.get("content", ""),
        )
    return _finish(
        ok=False,
        result=last_content or None,
        error="Max turns reached without a final answer.",
        turns=max_turns,
    )


def _cli_confirm(tool_name: str, args: dict) -> bool:
    print(f"\n⚠️  Agent wants to call: {tool_name}({args})")
    answer = input("Allow? [y/N]: ").strip().lower()
    return answer == "y"


def build_system_prompt(base_prompt: str, skill_catalog: list[dict]) -> str:
    skills_section = "\n".join(
        f"- {s['name']} (skill_path: {s['path']}): {s['description']}"
        for s in skill_catalog
    )
    workspace_root = Path.cwd()
    return (
        base_prompt
        + f"\n\n## Workspace\nThe project working directory is: {workspace_root}\n"
        f"Skills live under ~/.amon/skills and are shared across projects — their paths are "
        f"absolute and unrelated to the workspace. When running `shell`/`shell_readonly` "
        f"commands (e.g. invoking a skill's script), always pass `cwd={workspace_root}` "
        f"(or a path inside it) unless the user asks you to operate elsewhere. Never infer "
        f"cwd from a skill's path."
        + f"\n\n## Available Skills\n{skills_section}\n\nWhen the user's request matches one of the above skills, your FIRST tool call MUST be `load_skill(skill_path=<path>)` using the skill_path shown. Do not run any shell commands or read any files before loading the skill."
    )
