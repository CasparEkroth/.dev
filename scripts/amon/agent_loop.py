"""Core agent turn loop: LLM calls, tool dispatch, hooks, compaction triggers.

Compaction helpers live in ``scripts.amon.compaction``; result/usage helpers and
``truncate_tool_output`` in ``scripts.amon.agent_result``; system-prompt assembly
in ``scripts.amon.system_prompt``. Symbols are re-exported here so existing
``from scripts.amon.agent_loop import …`` call sites and test patches keep
working unchanged.
"""

from __future__ import annotations

from typing import Callable
from uuid import UUID
import os
import json
import time

from config import (
    COMPACT_AT_TOKENS,
    DEFAULT_MAX_TURNS,
    MAX_TOOL_OUTPUT_CHARS,
    TOOL_OUTPUT_DIR,
)
from scripts.amon.agent_result import (
    AgentResult,
    _add_usage,
    _empty_usage,
    _preview,
    _turn_usage,
    file_event_log,
    truncate_tool_output,
)
from scripts.amon.compaction import (
    _compact_history,
    _compaction_plan,
    _force_hard_trim,
    _render_compact_summary,
    _strip_unfinished_tool_turns,
    compact_conversation,
)
from scripts.amon.hooks import HookEventName, run_hook_event
from scripts.amon.memory import (
    save_context_tokens,
    save_session,
    save_session_info,
    load_session,
)
from scripts.amon.system_prompt import (
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    build_system_prompt,
)
from scripts.amon.tools.todo import get_todos, render_todos
from shared.llm_client import call_llm_with_tools

# Re-export public + test-patched symbols at this module path.
__all__ = [
    "AgentResult",
    "DEFAULT_SYSTEM_PROMPT_TEMPLATE",
    "build_system_prompt",
    "compact_conversation",
    "file_event_log",
    "run_agent",
    "truncate_tool_output",
    "_add_usage",
    "_compact_history",
    "_compaction_plan",
    "_empty_usage",
    "_force_hard_trim",
    "_preview",
    "_render_compact_summary",
    "_strip_unfinished_tool_turns",
    "_turn_usage",
]


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
    hooks: dict[str, list[dict]] | None = None,
    force_first_tool: bool = False,
    max_runtime_s: float | None = None,
    model: str | None = None,
    compact_at_tokens: int = COMPACT_AT_TOKENS,
    system_prompt_template: str | None = None,
    max_tool_output_chars: int | None = None,
    agent_name: str | None = None,
    event_log: Callable[[dict], None] | None = None,
    cancel_fn: Callable[[], bool] | None = None,
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
    event_log: optional sink for structured observability events
        ({"ts", "session_id", "event", ...}, event in "turn" / "tool_call" /
        "tool_result" / "compact"). None (default) means no logging
        whatsoever — this is opt-in, not always-on, so a normal run pays no
        cost. Callers gate it behind AMON_EVENTS, same pattern as
        AMON_STREAM for stream_actions.
    agent_name: recorded once in the session's .meta.json (with a preview of
        this turn's task) on a brand-new session, so `/sessions` and
        `--resume` show more than a bare UUID. Cosmetic only.
    cancel_fn: optional callable polled between turns and between individual
        tool calls within a turn; a truthy return stops the run at the next
        checkpoint (not mid-tool-call — an in-flight tool still finishes).
        The partial run is persisted and returned as a normal, non-ok
        AgentResult with error="interrupted", same shape as hitting
        max_turns or max_runtime_s. None (default) disables this entirely.
    """
    from scripts.amon.terminal import confirm_tool, stream_action

    hooks = hooks or {}
    tool_definitions = [t["schema"] for t in tool_registry.values()]
    confirm_fn = confirm_fn or confirm_tool
    # A caller-provided stream_actions (e.g. run_task's stream_action_stderr
    # for AMON_STREAM) must win even in headless mode — operator precedence
    # here used to parse as `(stream_actions or stream_action) if not
    # headless else None`, which discarded any caller override whenever
    # headless was True. The interactive default (`stream_action`) still
    # only kicks in when nothing was passed AND we're not headless.
    stream_actions = stream_actions or (None if headless else stream_action)
    token_fn = token_fn if not headless else None

    system_prompt = build_system_prompt(
        system_prompt, skill_catalog, system_prompt_template
    )
    # Sanitize on load: a prior run interrupted (Ctrl+C, crash) between
    # persisting an assistant's tool_calls and appending the matching tool
    # replies leaves an incomplete cycle on disk. Sending that straight to
    # the API breaks the request; stripping it here is a no-op for any
    # session that ended cleanly.
    history = (
        _strip_unfinished_tool_turns(load_session(session_id)) if session_id else []
    )
    conversation = history + [{"role": "user", "content": user_input}]
    new_messages = [{"role": "user", "content": user_input}]

    tools_used: list[str] = []
    last_usage = _empty_usage()
    accumulated_usage = _empty_usage()
    last_content = ""
    active_session_id = session_id

    session_info_saved = False

    def _persist(usage_dict: dict) -> None:
        nonlocal active_session_id, new_messages, session_info_saved
        if not save_session_:
            return
        active_session_id = save_session(new_messages, session_id=active_session_id)
        if active_session_id:
            save_context_tokens(active_session_id, usage_dict.get("prompt_tokens", 0))
            if not history and not session_info_saved:
                save_session_info(
                    active_session_id, agent=agent_name, preview=_preview(user_input)
                )
                session_info_saved = True
        new_messages = []

    def _log_event(event_type: str, **fields) -> None:
        if not event_log:
            return
        event_log(
            {
                "ts": time.time(),
                "session_id": str(active_session_id) if active_session_id else None,
                "event": event_type,
                **fields,
            }
        )

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
        if not stdout.strip():
            return
        message = {"role": "user", "content": stdout.strip()}
        conversation.append(message)
        new_messages.append(message)

    if not history:
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

    if history and active_session_id:
        existing_todos = get_todos(str(active_session_id))
        if existing_todos:
            _inject(
                "Resuming this session — existing checklist (call todo_write "
                "to update it):\n" + render_todos(existing_todos)
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

        if cancel_fn is not None and cancel_fn():
            stop_error = "Interrupted."
            turns_taken = turn
            break

        # Skip the extra monotonic() calls entirely when nobody's listening —
        # avoids the cost, and avoids perturbing time.monotonic call counts
        # for anything mocking the clock (e.g. the time-budget tests).
        turn_started_at = time.monotonic() if event_log else None
        try:
            response = call_llm_with_tools(
                system_prompt,
                conversation,
                tool_definitions,
                force_tool=force_first_tool and turn == 0 and bool(tool_definitions),
                model=model,
            )
        except Exception as exc:  # noqa: BLE001
            if retried:
                if _force_hard_trim(conversation):
                    retried = False
                    _log_event("compact", trigger="retry", method="hard_trim")
                    continue
                stop_error = f"Model call failed: {exc}"
                turns_taken = turn + 1
                break
            if _compact_history(conversation):
                retried = True
                _log_event("compact", trigger="retry", method="summary")
                continue
            if _force_hard_trim(conversation):
                retried = True
                _log_event("compact", trigger="retry", method="hard_trim")
                continue
            stop_error = f"Model call failed: {exc}"
            turns_taken = turn + 1
            break

        retried = False

        choice = response["choices"][0]
        message = choice["message"]
        last_usage = _turn_usage(response.get("usage"))
        accumulated_usage = _add_usage(accumulated_usage, last_usage)
        last_content = message.get("content") or last_content
        if event_log:
            _log_event(
                "turn",
                turn=turn + 1,
                latency_s=round(time.monotonic() - turn_started_at, 3),
                usage=last_usage,
            )

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

        _persist(last_usage)

        interrupted_mid_turn = False
        post_tool_hook_output: list[str] = []
        for call in tool_calls:
            if cancel_fn is not None and cancel_fn():
                interrupted_mid_turn = True
                break

            name = call["function"]["name"]
            tools_used.append(name)
            tool_started_at = time.monotonic() if event_log else None
            entry = tool_registry.get(name)
            try:
                args = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError as exc:
                args, arg_error = {}, f"Invalid arguments JSON: {exc}"
            else:
                arg_error = None

            if entry is None:
                result = (
                    f"Unknown tool '{name}'. Available: "
                    f"{', '.join(sorted(tool_registry))}"
                )
            elif arg_error:
                result = arg_error
            elif headless and entry["requires_confirmation"]:
                result = (
                    f"Agent is running in headless mode and doesn't have "
                    f"permission to run tool {name}."
                )
            else:
                # confirm_fn may return a bare bool (legacy / simple custom
                # confirm_fn) or (allowed, reason) — a denial reason the
                # user typed, fed back so the model can course-correct
                # instead of just retrying blind.
                allowed, deny_reason = True, None
                if entry["requires_confirmation"]:
                    confirmation = confirm_fn(name, args)
                    allowed, deny_reason = (
                        confirmation
                        if isinstance(confirmation, tuple)
                        else (confirmation, None)
                    )

                if not allowed:
                    result = (
                        f"User denied permission to run tool '{name}' with "
                        f"args {args}."
                    )
                    if deny_reason:
                        result += f" Reason: {deny_reason}"
                else:
                    fn = entry["fn"]
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
                        _log_event("tool_call", name=name)
                        result = (
                            f"Tool blocked by hook: {blocked}"
                            if blocked
                            else fn(**args)
                        )
                    except Exception as e:
                        _persist(last_usage)
                        result = f"Error: {e}"
            output = truncate_tool_output(
                str(result),
                tool=name,
                session_id=active_session_id,
                limit=max_tool_output_chars or MAX_TOOL_OUTPUT_CHARS,
                spill_dir=TOOL_OUTPUT_DIR,
            )
            if event_log:
                _log_event(
                    "tool_result",
                    name=name,
                    latency_s=round(time.monotonic() - tool_started_at, 3),
                    output_chars=len(output),
                )
            tool_msg = {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": output,
            }

            post_out, _ = run_hook_event(
                specs=hooks.get(HookEventName.POST_TOOL_USE, []),
                session_id=active_session_id,
                hook_event_name=HookEventName.POST_TOOL_USE,
                cwd=os.getcwd(),
                tool_name=name,
                tool_input=args,
                tool_output=output,
            )
            if post_out.strip():
                post_tool_hook_output.append(post_out.strip())

            if stream_actions:
                stream_actions("tool_result", {"name": name, "content": output})
            conversation.append(tool_msg)
            new_messages.append(tool_msg)

        # postToolUse hooks (e.g. a test-gate) are context-contributing like
        # agentSpawn/start: their combined stdout joins the conversation as
        # its own message after the turn's tool replies, never interleaved
        # between them (the API requires every tool_calls entry to be
        # followed immediately by its own tool reply, nothing else).
        _inject("\n\n".join(post_tool_hook_output))

        if interrupted_mid_turn:
            stop_error = "Interrupted."
            turns_taken = turn + 1
            break

        if token_fn:
            token_fn(
                tokens_added=last_usage["total_tokens"],
                context=last_usage["prompt_tokens"],
            )

        if last_usage["prompt_tokens"] > compact_at_tokens:
            if _compact_history(conversation):
                _log_event(
                    "compact",
                    trigger="threshold",
                    method="summary",
                    prompt_tokens=last_usage["prompt_tokens"],
                )
            else:
                _force_hard_trim(conversation)
                _log_event(
                    "compact",
                    trigger="threshold",
                    method="hard_trim",
                    prompt_tokens=last_usage["prompt_tokens"],
                )

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
