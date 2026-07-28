from pathlib import Path
from uuid import UUID
import os

from scripts.amon.hooks import HookEventName, run_hook_event
from scripts.amon.memory import save_context_tokens, save_session, load_session
from shared.llm_client import call_llm_with_tools
import json


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
) -> str:
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

    if hooks.get(HookEventName.START):
        run_hook_event(
            path=hooks.get(HookEventName.START),
            session_id=session_id,
            hook_event_name=HookEventName.START,
            cwd=os.getcwd(),
            prompt=user_input,
        )

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
        usage = response["usage"]

        conversation.append(message)
        new_messages.append(message)

        if message.get("content") and stream_actions:
            stream_actions("reasoning", {"content": message["content"]})

        tool_calls = message.get("tool_calls")
        # print(f"[DEBUG] content={repr(message.get('content'))[:120]} tool_calls={bool(tool_calls)}")
        if not tool_calls:
            if save_session_:
                save_session(new_messages, session_id=session_id)
                if session_id:
                    save_context_tokens(session_id, usage["prompt_tokens"])

            if hooks.get(HookEventName.STOP):
                run_hook_event(
                    path=hooks.get(HookEventName.STOP),
                    session_id=session_id,
                    hook_event_name=HookEventName.STOP,
                    cwd=os.getcwd(),
                    response=message.get("content", ""),
                )
            return message.get("content", "")

        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])

            fn = tool_registry[name]["fn"]
            need_confirmation = tool_registry[name]["requires_confirmation"]
            if headless and need_confirmation:
                result = f"Agent is running in headless mode and doesn't have permission to run tool {name}."
            elif need_confirmation and not confirm_fn(name, args):
                result = (
                    f"User denied permission to run tool '{name}' with args {args}."
                )
            else:
                try:
                    if hooks.get(HookEventName.PRE_TOOL_USE):
                        run_hook_event(
                            path=hooks.get(HookEventName.PRE_TOOL_USE),
                            session_id=session_id,
                            hook_event_name=HookEventName.PRE_TOOL_USE,
                            cwd=os.getcwd(),
                            tool_name=name,
                            tool_input=args,
                        )

                    stream_actions("tool_call", {"name": name, "args": args})
                    result = fn(**args)
                except Exception as e:
                    if save_session_:
                        save_session(new_messages, session_id=session_id)
                        if session_id:
                            save_context_tokens(session_id, usage["prompt_tokens"])
                    result = f"Error: {e}"
            tool_msg = {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": str(result),
            }

            if hooks.get(HookEventName.POST_TOOL_USE):
                run_hook_event(
                    path=hooks.get(HookEventName.POST_TOOL_USE),
                    session_id=session_id,
                    hook_event_name=HookEventName.POST_TOOL_USE,
                    cwd=os.getcwd(),
                    tool_name=name,
                    tool_input=args,
                    tool_output=str(result),
                )

            stream_actions("tool_result", {"name": name, "content": str(result)})
            conversation.append(tool_msg)
            new_messages.append(tool_msg)

        token_fn(tokens_added=usage["total_tokens"], context=usage["prompt_tokens"])

    if save_session_:
        save_session(new_messages, session_id=session_id)
        if session_id:
            save_context_tokens(session_id, usage["prompt_tokens"])

    if hooks.get(HookEventName.STOP):
        run_hook_event(
            path=hooks.get(HookEventName.STOP),
            session_id=session_id,
            hook_event_name=HookEventName.STOP,
            cwd=os.getcwd(),
            response=message.get("content", ""),
        )
    return "Max turns reached without a final answer."


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
