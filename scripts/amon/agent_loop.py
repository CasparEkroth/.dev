from uuid import UUID

from scripts.amon.memory import save_session, load_session
from shared.llm_client import call_llm_with_tools
import json


def run_agent(
    system_prompt: str,
    user_input: str,
    tool_registry: dict,
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

    conversation = load_session(session_id) if session_id else []
    conversation.append({"role": "user", "content": user_input})

    for _ in range(max_turns):
        message = call_llm_with_tools(system_prompt, conversation, tool_definitions)
        conversation.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            if save_session_:
                save_session(conversation, session_id=session_id)
            return message.get("content", "")

        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])

            fn = tool_registry[name]["fn"]
            need_confirmation = tool_registry[name]["requires_confirmation"]
            if headless and need_confirmation:
                result = f"Agnet is running in headless and dosen't have prmission to run tool {name}."

            elif need_confirmation and not confirm_fn(name, args):
                result = (
                    f"User denied permission to run tool '{name}' with args {args}."
                )
            else:
                try:
                    result = fn(**args)
                except Exception as e:
                    if save_session_:
                        save_session(conversation, session_id=session_id)
                    result = f"Error: {e}"

            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": str(result),
                }
            )
    if save_session_:
        save_session(conversation, session_id=session_id)
    return "Max turns reached without a final answer."


def _cli_confirm(tool_name: str, args: dict) -> bool:
    print(f"\n⚠️  Agent wants to call: {tool_name}({args})")
    answer = input("Allow? [y/N]: ").strip().lower()
    return answer == "y"
