import re
import json
import uuid
import requests
from config import settings


def _parse_xml_tool_calls(content: str) -> list[dict] | None:
    """Parse <tool_call>...</tool_call> blocks that some models emit instead of structured tool_calls."""
    blocks = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", content, re.DOTALL)
    if not blocks:
        return None
    calls = []
    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        name = data.get("name") or data.get("function")
        arguments = data.get("arguments") or data.get("parameters") or {}
        calls.append(
            {
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }
        )
    return calls or None


def call_llm_with_config(base_url: str, api_key: str, model: str, prompt: str) -> str:
    endpoint = base_url.rstrip("/")

    if not endpoint.endswith(("/chat/completions", "/responses")):
        endpoint = f"{endpoint}/chat/completions"

    r = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        },
        timeout=60,
    )

    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def call_llm(prompt: str) -> str:
    return call_llm_with_config(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
        prompt=prompt,
    )


def call_llm_with_tools(
    system_prompt: str,
    conversation_history: dict,
    tool_definitions: dict,
) -> dict:
    messages = [{"role": "system", "content": system_prompt}] + conversation_history

    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
    }
    if tool_definitions:
        payload["tools"] = tool_definitions
        payload["tool_choice"] = "auto"

    endpoint = settings.LLM_BASE_URL.rstrip("/")
    if not endpoint.endswith(("/chat/completions", "/responses")):
        endpoint = f"{endpoint}/chat/completions"

    r = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(10, 180),
    )
    r.raise_for_status()
    message = r.json()["choices"][0]["message"]

    if not message.get("tool_calls") and message.get("content"):
        parsed = _parse_xml_tool_calls(message["content"])
        if parsed:
            message = {**message, "tool_calls": parsed, "content": None}

    return message
