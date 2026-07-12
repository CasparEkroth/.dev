import requests
from config import settings


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
    return r.json()["choices"][0]["message"]
