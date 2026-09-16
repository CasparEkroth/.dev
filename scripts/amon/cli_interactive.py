"""Interactive REPL loop for `amon` (session commands + agent turns)."""

from __future__ import annotations

import asyncio
import os
import signal
from uuid import UUID, uuid4

from scripts.amon.agent_loop import (
    _compact_history,
    _compaction_plan,
    file_event_log,
    run_agent,
)
from scripts.amon import terminal
from scripts.amon.memory import (
    agent_mismatch_warning,
    get_list_of_sessions,
    load_context_tokens,
    load_session,
    save_session,
)
from scripts.amon.tools.mcp import discover_mcp_tools
from scripts.amon.tools.registry import READY_AGENTS, get_registry
from scripts.amon.tools.skills import catalog_for_agent


def _run_agent_cancelable(**kwargs):
    """run_agent, but a first Ctrl+C requests a graceful stop instead of an
    immediate hard abort.

    Installs a SIGINT handler for the duration of the call that sets a flag
    run_agent polls between turns and between tool calls within a turn — the
    current step (an in-flight LLM/tool call) still finishes, then the
    partial run is persisted and returned normally as a non-ok AgentResult.
    A second Ctrl+C while still running restores default SIGINT behavior and
    raises KeyboardInterrupt immediately, same as the old hard-cancel-only
    behavior — the caller's existing `except KeyboardInterrupt` handles that.
    """
    cancelled = {"requested": False}

    def _handler(signum, frame):
        if cancelled["requested"]:
            signal.default_int_handler(signum, frame)
            return
        cancelled["requested"] = True
        terminal.console.print(
            "\n[yellow]Stopping after the current step… "
            "press Ctrl+C again to force quit.[/yellow]"
        )

    previous_handler = signal.signal(signal.SIGINT, _handler)
    try:
        return run_agent(cancel_fn=lambda: cancelled["requested"], **kwargs)
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def _discover_agent_mcp_tools(agent) -> tuple[dict | None, list]:
    """Discover *agent*'s MCP-backed tools once (not per prompt).

    The interactive loop is sync top-to-bottom; this is the same
    `asyncio.run(...)` bridging idiom `registry.py`'s `_spawn_agents` already
    uses, just for a different sync/async boundary. Returns ``(None, [])``
    when the agent has no `mcp_servers` configured so callers can pass the
    tools dict straight through as `get_registry`'s `extra_tools`. The second
    element is a list of zero-arg closers for any persistent MCP connections
    opened during discovery — callers must run them on agent switch / exit.
    """
    if not agent.mcp_servers:
        return None, []
    tools, closers = asyncio.run(discover_mcp_tools(agent.mcp_servers))
    return tools, closers


def _close_mcp(closers: list) -> None:
    for closer in closers:
        try:
            closer()
        except Exception:
            pass


def _sorted_sessions():
    sessions = get_list_of_sessions()
    sessions.sort(key=lambda x: x[1], reverse=True)
    return sessions


def _resolve_session_id(args) -> UUID | None:
    if args.resume_id:
        return args.resume_id
    if args.resume:
        sessions = _sorted_sessions()
        picked = terminal.pick_session(sessions)
        if picked == "[cancel]" or picked is None:
            return None
        return UUID(picked.name)
    return uuid4()


def _run_interactive(args) -> None:
    session_id = _resolve_session_id(args)
    if session_id is None:
        return

    # A resumed session recorded which agent last ran it; a mismatch here
    # is almost always the user forgetting --agent, not an intentional
    # switch — the /agent picker is the intentional path.
    warning = agent_mismatch_warning(session_id, args.agent)
    if warning:
        terminal.console.print(f"[yellow]{warning}[/yellow]")

    terminal.update_footer(context=load_context_tokens(session_id))
    terminal.show_welcome(session_id)
    prompt_session = terminal.make_prompt_session()
    agent = READY_AGENTS.get(args.agent, None)

    if agent is None:
        terminal.console.print(f"Error: {args.agent} is not a saved agent")
        return

    mcp_tools, mcp_closers = _discover_agent_mcp_tools(agent)

    try:
        while True:
            try:
                user_input = prompt_session.prompt("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                terminal.console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue

            if user_input in ("/exit", "/quit", "/q"):
                terminal.console.print("[dim]Goodbye.[/dim]")
                break

            if user_input == ("/agent"):
                t_agent = terminal.pick_agents()
                if t_agent is None or t_agent == "[cancel]":
                    terminal.console.print("[dim]No agent picked.[/dim]")
                    terminal.console.print(f"[dim]Current agent: {agent.name}")
                    continue
                # Tear down the previous agent's persistent MCP connections
                # before opening the next agent's — ordering matters so we
                # don't leak the old connection across the switch.
                _close_mcp(mcp_closers)
                agent = READY_AGENTS.get(t_agent)
                mcp_tools, mcp_closers = _discover_agent_mcp_tools(agent)
                continue

            if user_input == "/sessions":
                terminal.print_sessions(_sorted_sessions())
                continue

            if user_input == "/new":
                session_id = uuid4()
                terminal.reset_context()
                terminal.console.print("[dim]New session started.[/dim]")
                continue

            if user_input == "/compact":
                conversation = load_session(session_id)
                if not conversation:
                    terminal.console.print("[dim]Session is empty.[/dim]")
                    continue
                if _compaction_plan(conversation) is None:
                    terminal.console.print("[dim]Nothing to compact yet.[/dim]")
                    continue
                # Same path the auto-compactor uses: strips any dangling
                # tool_calls first and only summarizes the safe head, keeping the
                # most recent complete tool cycle verbatim — the plain
                # compact_conversation() call this replaced had neither
                # protection and could silently drop in-flight tool state.
                with terminal.spinner_context():
                    ok = _compact_history(conversation)
                if not ok:
                    terminal.console.print(
                        "[red]Compact failed: model did not return valid JSON.[/red]"
                    )
                    continue
                save_session(
                    conversation=conversation,
                    session_id=session_id,
                    override=True,
                )
                terminal.console.print("[dim]Session compacted.[/dim]")
                terminal.update_footer(context="-")
                continue

            if str(user_input).startswith("/"):
                terminal.console.print(
                    f"[dim]{user_input.split()[0]} is not a command.[/dim]"
                )
                continue

            with terminal.spinner_context():
                try:
                    result = _run_agent_cancelable(
                        system_prompt=agent.system_prompt,
                        user_input=user_input,
                        tool_registry=get_registry(
                            tools=agent.tools,
                            allowed_tools=agent.allowed_tools,
                            allow_paths=agent.allow_paths,
                            deny_paths=agent.deny_paths,
                            denied_commands=agent.denied_commands,
                            session_id=session_id,
                            extra_tools=mcp_tools,
                        ),
                        skill_catalog=catalog_for_agent(agent.allowed_skills),
                        confirm_fn=terminal.confirm_tool,
                        stream_actions=terminal.stream_action,
                        token_fn=terminal.update_footer,
                        session_id=session_id,
                        save_session_=True,
                        hooks=agent.hooks,
                        max_turns=agent.max_turns,
                        force_first_tool=agent.force_first_tool,
                        max_runtime_s=agent.max_runtime_s,
                        model=agent.model,
                        system_prompt_template=agent.system_prompt_template,
                        max_tool_output_chars=agent.max_tool_output_chars,
                        agent_name=agent.name,
                        event_log=(
                            file_event_log if os.environ.get("AMON_EVENTS") else None
                        ),
                    )
                except KeyboardInterrupt:
                    # Hard cancel: in-flight HTTP is aborted; no delayed receive.
                    # ESC is not handled — only Ctrl+C raises KeyboardInterrupt.
                    terminal.console.print("\n[yellow]Interrupted.[/yellow]")
                    continue

                # Clear the live checklist once the task is actually done — a
                # failed/interrupted run keeps it, since the leftover state (e.g.
                # what was still 'in_progress') is useful context for why it
                # stopped there. Only a clean finish resets the footer.
                if result.ok:
                    terminal.footer.reset_footer(todos=True)

                # Streaming already showed content; surface structured failure meta.
                if not result.ok:
                    err = result.error or "Agent run failed."
                    terminal.console.print(f"[red]{err}[/red]")
                    meta_parts = []
                    if result.usage.get("total_tokens"):
                        meta_parts.append(f"tokens={result.usage['total_tokens']}")
                    if result.turns:
                        meta_parts.append(f"turns={result.turns}")
                    if result.tools_used:
                        meta_parts.append(f"tools={', '.join(result.tools_used)}")
                    if meta_parts:
                        terminal.console.print(f"[dim]{' · '.join(meta_parts)}[/dim]")
    finally:
        _close_mcp(mcp_closers)
