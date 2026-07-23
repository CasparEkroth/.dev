import json
import re
import uuid
import requests
from config import settings
from shared.llm_types import (
    ChatCompletionResponse,
    ToolCall,
    ToolCallFunction,
)


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


def parse_llm_json(text: str) -> list | dict | None:
    """Parse a JSON value out of an LLM text response, tolerating ```json fences."""
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


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


def get_context_window(base_url: str, api_key: str, model: str) -> int | None:
    """Look up the context-window size for `model` from the provider's model-listing
    endpoint. Returns None if the endpoint is unavailable, unreachable, or doesn't
    list the model (e.g. non-xAI providers)."""
    endpoint = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
            break
    endpoint = f"{endpoint}/language-models"

    try:
        r = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        r.raise_for_status()
        models = r.json().get("models", [])
    except (requests.RequestException, ValueError):
        return None

    for m in models:
        if model == m.get("id") or model in m.get("aliases", []):
            return m.get("long_context_threshold")
    return None


def call_llm_with_tools(
    system_prompt: str,
    conversation_history: dict,
    tool_definitions: dict,
    force_tool: bool = False,
) -> dict:
    messages = [{"role": "system", "content": system_prompt}] + conversation_history

    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
    }
    if tool_definitions:
        payload["tools"] = tool_definitions
        payload["tool_choice"] = "required" if force_tool else "auto"

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
    raw = r.json()
    response = ChatCompletionResponse.model_validate(raw)

    message = response.choices[0].message

    # Fallback: some models still return XML tool calls
    if not message.tool_calls and message.content:
        parsed = _parse_xml_tool_calls(message.content)
        if parsed:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    function=ToolCallFunction(
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    ),
                )
                for tc in parsed
            ]
            message = message.model_copy(
                update={"tool_calls": tool_calls, "content": None}
            )
            # Update the response with the fixed message
            response = response.model_copy(
                update={
                    "choices": [
                        response.choices[0].model_copy(update={"message": message})
                    ]
                }
            )

    return response.model_dump()
