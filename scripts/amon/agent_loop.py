from uuid import UUID

from scripts.amon.memory import save_session, load_session
from shared.llm_client import call_llm_with_tools
import json


def run_agent(
    system_prompt: str,
    user_input: str,
    tool_registry: dict,
    skill_catalog: dict,
    max_turns: int = 30,
    confirm_fn=None,
    session_id: UUID = None,
    save_session_: bool = True,
    headless: bool = False,
) -> str:
    """
    tool_registry: {"send_email": {"schema": {...}, "fn": callable}, ...}
    """
    tool_definitions = [t["schema"] for t in tool_registry.values()]
    confirm_fn = confirm_fn or _cli_confirm

    system_prompt = build_system_prompt(system_prompt, skill_catalog)
    history = load_session(session_id) if session_id else []
    conversation = history + [{"role": "user", "content": user_input}]
    new_messages = [{"role": "user", "content": user_input}]

    for _ in range(max_turns):
        message = call_llm_with_tools(system_prompt, conversation, tool_definitions)
        conversation.append(message)
        new_messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            if save_session_:
                save_session(new_messages, session_id=session_id)
            return message.get("content", "")

        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])

            fn = tool_registry[name]["fn"]
            need_confirmation = tool_registry[name]["requires_confirmation"]
            if headless and need_confirmation:
                result = f"Agent is running in headless mode and doesn't have permission to run tool {name}."
            elif need_confirmation and not confirm_fn(name, args):
                result = f"User denied permission to run tool '{name}' with args {args}."
            else:
                try:
                    result = fn(**args)
                except Exception as e:
                    if save_session_:
                        save_session(new_messages, session_id=session_id)
                    result = f"Error: {e}"

            tool_msg = {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": str(result),
            }
            conversation.append(tool_msg)
            new_messages.append(tool_msg)

    if save_session_:
        save_session(new_messages, session_id=session_id)
    return "Max turns reached without a final answer."


def _cli_confirm(tool_name: str, args: dict) -> bool:
    print(f"\n⚠️  Agent wants to call: {tool_name}({args})")
    answer = input("Allow? [y/N]: ").strip().lower()
    return answer == "y"


def build_system_prompt(base_prompt: str, skill_catalog: list[dict]) -> str:
    skills_section = "\n".join(
        f"- {s['name']}: {s['description']}" for s in skill_catalog
    )
    return (
        base_prompt
        + f"\n\n## Available Skills\n{skills_section}\n\nCall `load_skill` to get full instructions before executing a skill."
    )
