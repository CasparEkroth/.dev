import requests


def call_llm(base_url: str, api_key: str, model: str, prompt: str):
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
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )

    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
