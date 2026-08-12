from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4
import os
import json
import time

from config import (
    COMPACT_AT_TOKENS,
    DEFAULT_MAX_TURNS,
    MAX_TOOL_OUTPUT_CHARS,
    TOOL_OUTPUT_DIR,
)
from scripts.amon.hooks import HookEventName, run_hook_event
from scripts.amon.memory import save_context_tokens, save_session, load_session
from shared.llm_client import call_llm, call_llm_with_tools, parse_llm_json


def compact_conversation(conversation: list[dict]) -> list[dict] | None:
    """Summarize *conversation* into a smaller message list, or None on failure.

    Sanitized to plain role/content: a summarized ``tool_calls`` turn would
    reference tool replies that no longer exist, which the provider rejects.
    """
    if not conversation:
        return None
    parsed = parse_llm_json(
        call_llm(
            f"summarize this conversation {conversation} return the summary as a "
            f"json in the same structure as the original but significant smaller."
        )
    )
    if not isinstance(parsed, list):
        return None
    return [
        {"role": m["role"], "content": str(m.get("content") or "")}
        for m in parsed
        if isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")
    ] or None


def _compact_history(conversation: list[dict]) -> bool:
    """Summarize *conversation* in place, up to the last tool-calling turn.

    Cutting there keeps surviving tool replies with the message they refer to.
    Returns False when the summary was unusable and nothing changed.
    """
    cut = next(
        (
            i
            for i in range(len(conversation) - 1, -1, -1)
            if conversation[i].get("tool_calls")
        ),
        len(conversation),
    )
    summary = compact_conversation(conversation[:cut])
    if not summary:
        return False
    conversation[:cut] = summary
    return True


def truncate_tool_output(
    text: str,
    tool: str = "",
    session_id: UUID | str | None = None,
    limit: int = MAX_TOOL_OUTPUT_CHARS,
    spill_dir: Path = TOOL_OUTPUT_DIR,
) -> str:
    """Cap one tool result at *limit*, keeping its head and tail.

    The full text is written to *spill_dir* and the marker names that file, so
    one verbose command cannot exhaust the context window and nothing is lost.
    """
    if len(text) <= limit:
        return text

    spill_dir.mkdir(parents=True, exist_ok=True)
    spill = (
        spill_dir
        / f"{session_id or 'nosession'}_{tool or 'tool'}_{uuid4().hex[:8]}.txt"
    )
    spill.write_text(text, encoding="utf-8")

    head_len = limit * 6 // 10
    tail_len = limit - head_len
    marker = (
        f"\n… [truncated {len(text) - limit} of {len(text)} chars — "
        f"full output: {spill} (read it with read_file)] …\n"
    )
    return f"{text[:head_len]}{marker}{text[-tail_len:]}"


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
    max_turns: int = DEFAULT_MAX_TURNS,
    confirm_fn=None,
    stream_actions=None,
    token_fn=None,
    session_id: UUID = None,
    save_session_: bool = True,
    headless: bool = False,
    hooks: dict[str, list[dict]] = {},
    force_first_tool: bool = False,
    max_runtime_s: float | None = None,
    model: str | None = None,
    compact_at_tokens: int = COMPACT_AT_TOKENS,
    system_prompt_template: str | None = None,
) -> AgentResult:
    """
    tool_registry: {"send_email": {"schema": {...}, "fn": callable}, ...}

    force_first_tool: require a tool call on turn 0. Off by default so an agent
        can open with a question.
    max_runtime_s: wall-clock budget; the run stops between turns and keeps its
        partial result.
    model: model id for this run; falls back to the configured default.
    compact_at_tokens: prompt size at which the history is summarized. Pass a
        large value to disable.
    system_prompt_template: overrides prompt assembly.
    """
    from scripts.amon.terminal import confirm_tool, stream_action

    tool_definitions = [t["schema"] for t in tool_registry.values()]
    confirm_fn = confirm_fn or confirm_tool
    stream_actions = stream_actions or stream_action if not headless else None
    token_fn = token_fn if not headless else None

    system_prompt = build_system_prompt(
        system_prompt, skill_catalog, system_prompt_template
    )
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

    def _inject(stdout: str) -> None:
        """Give the model a hook's output, and keep it in the session."""
        if not stdout.strip():
            return
        message = {"role": "user", "content": stdout.strip()}
        conversation.append(message)
        new_messages.append(message)

    if not history:
        # Closest thing to "agent activated": the first turn of a session.
        _inject(
            run_hook_event(
                specs=hooks.get(HookEventName.AGENT_SPAWN, []),
                session_id=active_session_id,
                hook_event_name=HookEventName.AGENT_SPAWN,
                cwd=os.getcwd(),
            )[0]
        )

    _inject(
        run_hook_event(
            specs=hooks.get(HookEventName.START, []),
            session_id=active_session_id,
            hook_event_name=HookEventName.START,
            cwd=os.getcwd(),
            prompt=user_input,
        )[0]
    )

    message = {"content": ""}
    started_at = time.monotonic()
    retried = False
    stop_error = "Max turns reached without a final answer."
    turns_taken = max_turns
    for turn in range(max_turns):
        if max_runtime_s is not None and time.monotonic() - started_at > max_runtime_s:
            stop_error = (
                f"Time budget of {max_runtime_s}s exceeded without a final answer."
            )
            turns_taken = turn
            break

        try:
            response = call_llm_with_tools(
                system_prompt,
                conversation,
                tool_definitions,
                force_tool=force_first_tool and turn == 0 and bool(tool_definitions),
                model=model,
            )
        # Degrade instead of losing the run: the stop hook and _persist still run.
        except Exception as exc:  # noqa: BLE001
            # A full context is the likeliest cause; shrink it and retry once.
            if not retried and _compact_history(conversation):
                retried = True
                continue
            stop_error = f"Model call failed: {exc}"
            turns_taken = turn + 1
            break

        retried = False

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
                    specs=hooks.get(HookEventName.STOP, []),
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
                    _, blocked = run_hook_event(
                        specs=hooks.get(HookEventName.PRE_TOOL_USE, []),
                        session_id=active_session_id,
                        hook_event_name=HookEventName.PRE_TOOL_USE,
                        cwd=os.getcwd(),
                        tool_name=name,
                        tool_input=args,
                    )
                    if stream_actions:
                        stream_actions("tool_call", {"name": name, "args": args})
                    result = (
                        f"Tool blocked by hook: {blocked}" if blocked else fn(**args)
                    )
                except Exception as e:
                    _persist(last_usage)
                    result = f"Error: {e}"
            # Passed explicitly so both knobs resolve per call.
            output = truncate_tool_output(
                str(result),
                tool=name,
                session_id=active_session_id,
                limit=MAX_TOOL_OUTPUT_CHARS,
                spill_dir=TOOL_OUTPUT_DIR,
            )
            tool_msg = {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": output,
            }

            run_hook_event(
                specs=hooks.get(HookEventName.POST_TOOL_USE, []),
                session_id=active_session_id,
                hook_event_name=HookEventName.POST_TOOL_USE,
                cwd=os.getcwd(),
                tool_name=name,
                tool_input=args,
                tool_output=output,
            )

            if stream_actions:
                stream_actions("tool_result", {"name": name, "content": output})
            conversation.append(tool_msg)
            new_messages.append(tool_msg)

        if token_fn:
            token_fn(
                tokens_added=last_usage["total_tokens"],
                context=last_usage["prompt_tokens"],
            )

        if last_usage["prompt_tokens"] > compact_at_tokens:
            _compact_history(conversation)

    _persist(last_usage)

    if hooks.get(HookEventName.STOP):
        run_hook_event(
            specs=hooks.get(HookEventName.STOP, []),
            session_id=active_session_id,
            hook_event_name=HookEventName.STOP,
            cwd=os.getcwd(),
            response=message.get("content", ""),
        )
    return _finish(
        ok=False,
        result=last_content or None,
        error=stop_error,
        turns=turns_taken,
    )


def _cli_confirm(tool_name: str, args: dict) -> bool:
    print(f"\n⚠️  Agent wants to call: {tool_name}({args})")
    answer = input("Allow? [y/N]: ").strip().lower()
    return answer == "y"


#: Placeholders: {prompt}, {workspace}, {skills}. An agent can replace this via
#: `system_prompt_template` — e.g. to drop the load_skill mandate. Literal braces
#: in a custom template must be doubled.
DEFAULT_SYSTEM_PROMPT_TEMPLATE = """{prompt}

## Workspace
The project working directory is: {workspace}
Skills live under ~/.amon/skills and are shared across projects — their paths are \
absolute and unrelated to the workspace. When running `shell`/`shell_readonly` \
commands (e.g. invoking a skill's script), always pass `cwd={workspace}` \
(or a path inside it) unless the user asks you to operate elsewhere. Never infer \
cwd from a skill's path.

## Available Skills
{skills}

When the user's request matches one of the above skills, your FIRST tool call \
MUST be `load_skill(skill_path=<path>)` using the skill_path shown. Do not run \
any shell commands or read any files before loading the skill."""


def build_system_prompt(
    base_prompt: str, skill_catalog: list[dict], template: str | None = None
) -> str:
    """Assemble the system prompt from *template* (or the default one)."""
    skills_section = "\n".join(
        f"- {s['name']} (skill_path: {s['path']}): {s['description']}"
        for s in skill_catalog
    )
    return (template or DEFAULT_SYSTEM_PROMPT_TEMPLATE).format(
        prompt=base_prompt, workspace=Path.cwd(), skills=skills_section
    )
