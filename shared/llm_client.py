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