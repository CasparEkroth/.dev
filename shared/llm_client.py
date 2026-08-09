"""LLM client built on the official OpenAI SDK.

Supports xAI (Grok), OpenAI, and Azure OpenAI. Provider selection is driven by
``settings.LLM_PROVIDER`` (or inferred from ``settings.LLM_BASE_URL``).
When ``LLM_PROVIDER == "azure"``, ``settings.LLM_MODEL`` is the Azure
deployment name, not a model id.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import httpx
from openai import AzureOpenAI, OpenAI

from config import settings
from shared.llm_types import (
    ChatCompletionResponse,
    ToolCall,
    ToolCallFunction,
)

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = frozenset({"xai", "azure", "openai"})

_client: OpenAI | AzureOpenAI | None = None
_client_provider: str | None = None


def reset_llm_client() -> None:
    """Drop the cached SDK client. Intended for tests."""
    global _client, _client_provider
    _client = None
    _client_provider = None


def resolve_provider(
    provider: str | None = None,
    base_url: str | None = None,
) -> str:
    """Return the canonical provider name (``xai`` | ``azure`` | ``openai``).

    With no arguments, resolves from ``settings`` (explicit ``LLM_PROVIDER``,
    else inferred from ``LLM_BASE_URL``). If *provider* or *base_url* is
    passed explicitly, settings are never consulted — the explicit value (or
    an inference from the given *base_url*) always wins, so callers hitting a
    different endpoint than ``settings`` can't be silently overridden by a
    global ``LLM_PROVIDER``. Raises ``ValueError`` for an explicit but
    unknown provider value.
    """
    if provider is None and base_url is None:
        provider = settings.LLM_PROVIDER
        base_url = settings.LLM_BASE_URL

    explicit = provider or None
    if explicit is not None:
        normalized = explicit.strip().lower()
        if normalized not in _VALID_PROVIDERS:
            raise ValueError(
                f"Unknown LLM_PROVIDER {explicit!r}; "
                f"expected one of {sorted(_VALID_PROVIDERS)}"
            )
        return normalized

    url_lower = (base_url or "").lower()
    if ".openai.azure.com" in url_lower:
        inferred = "azure"
    elif "x.ai" in url_lower:
        inferred = "xai"
    else:
        inferred = "openai"
    logger.info(
        "LLM_PROVIDER unset; inferred %r from LLM_BASE_URL=%r",
        inferred,
        base_url,
    )
    return inferred


def _normalize_base_url(base_url: str) -> str:
    """Strip a trailing chat-completions / responses suffix if present."""
    endpoint = (base_url or "").rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
            break
    return endpoint


def get_llm_client() -> OpenAI | AzureOpenAI:
    """Return a cached OpenAI / AzureOpenAI client for the configured provider."""
    global _client, _client_provider
    provider = resolve_provider()
    if _client is not None and _client_provider == provider:
        return _client

    # 10s connect / 120s read matches the previous tool-path requests timeout.
    timeout = httpx.Timeout(120.0, connect=10.0)
    api_key = settings.LLM_API_KEY

    if provider == "azure":
        _client = AzureOpenAI(
            azure_endpoint=_normalize_base_url(settings.LLM_BASE_URL),
            api_key=api_key,
            api_version=settings.AZURE_API_VERSION,
            max_retries=3,
            timeout=timeout,
        )
    else:
        _client = OpenAI(
            base_url=_normalize_base_url(settings.LLM_BASE_URL) or None,
            api_key=api_key,
            max_retries=3,
            timeout=timeout,
        )
    _client_provider = provider
    return _client


def _apply_reasoning_overrides(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Translate / drop params that reasoning models reject.

    When ``settings.LLM_REASONING_MODEL`` is true:
    - ``max_tokens`` becomes ``max_completion_tokens``
    - ``temperature``, ``top_p``, ``presence_penalty``, ``frequency_penalty``
      are removed
    """
    if not settings.LLM_REASONING_MODEL:
        return kwargs
    out = dict(kwargs)
    if "max_tokens" in out:
        out["max_completion_tokens"] = out.pop("max_tokens")
    for key in (
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
    ):
        out.pop(key, None)
    return out


def _tool_choice_value(force_tool: bool) -> str:
    """Build the ``tool_choice`` argument for a chat-completions call.

    ``"required"`` means the model must call *some* tool (any of the
    provided definitions). Azure OpenAI has supported this since API
    version ``2024-06-01``; our default ``AZURE_API_VERSION`` is newer.
    """
    return "required" if force_tool else "auto"


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


def _normalize_xml_tool_calls(
    response: ChatCompletionResponse,
) -> ChatCompletionResponse:
    """If the message has XML tool calls in content, promote them to tool_calls."""
    message = response.choices[0].message
    if message.tool_calls or not message.content:
        return response
    parsed = _parse_xml_tool_calls(message.content)
    if not parsed:
        return response
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
    message = message.model_copy(update={"tool_calls": tool_calls, "content": None})
    return response.model_copy(
        update={
            "choices": [response.choices[0].model_copy(update={"message": message})]
        }
    )


def parse_llm_json(text: str) -> list | dict | None:
    """Parse a JSON value out of an LLM text response, tolerating ```json fences."""
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def call_llm_with_config(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    provider: str | None = None,
) -> str:
    """Chat-completion helper that takes explicit connection parameters.

    Builds a one-off client (does not touch the process-wide cache) so callers
    can target a different endpoint than ``settings``. Pass *provider*
    explicitly when it can't be inferred from *base_url* (e.g. a custom Azure
    gateway domain).
    """
    resolved = resolve_provider(provider=provider, base_url=base_url)
    timeout = httpx.Timeout(60.0, connect=10.0)
    if resolved == "azure":
        client: OpenAI | AzureOpenAI = AzureOpenAI(
            azure_endpoint=_normalize_base_url(base_url),
            api_key=api_key,
            api_version=settings.AZURE_API_VERSION,
            max_retries=3,
            timeout=timeout,
        )
    else:
        client = OpenAI(
            base_url=_normalize_base_url(base_url) or None,
            api_key=api_key,
            max_retries=3,
            timeout=timeout,
        )

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    kwargs = _apply_reasoning_overrides(kwargs)
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    return content or ""


def call_llm(prompt: str) -> str:
    """Send a single user prompt via the configured provider and return the text."""
    client = get_llm_client()
    # settings.LLM_MODEL is the Azure deployment name when LLM_PROVIDER == "azure".
    kwargs: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    kwargs = _apply_reasoning_overrides(kwargs)
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    return content or ""


def get_context_window(
    base_url: str,
    api_key: str,
    model: str,
    provider: str | None = None,
) -> int | None:
    """Look up the context-window size for `model` from the provider's API.

    Only xAI exposes a model-listing endpoint with context-window data
    (``/language-models``); other providers have no such API, so this
    returns ``None`` for them. Pass *provider* explicitly when it can't be
    inferred from *base_url* (e.g. a custom Azure gateway domain) — omitting
    it does not fall back to ``settings.LLM_PROVIDER``. Never raises.
    """
    try:
        resolved = resolve_provider(provider=provider, base_url=base_url)
    except ValueError:
        return None

    if resolved == "xai":
        return _xai_context_window(base_url, api_key, model)

    return None


def _xai_context_window(base_url: str, api_key: str, model: str) -> int | None:
    """Query xAI's /language-models endpoint for the long-context threshold."""
    endpoint = _normalize_base_url(base_url)
    endpoint = f"{endpoint}/language-models"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
            models = r.json().get("models", [])
    except (httpx.HTTPError, ValueError, KeyError):
        return None

    for m in models:
        if model == m.get("id") or model in m.get("aliases", []):
            return m.get("long_context_threshold")
    return None


def call_llm_with_tools(
    system_prompt: str,
    conversation_history: list,
    tool_definitions: list | dict | None,
    force_tool: bool = False,
) -> dict:
    """Chat completion with optional tool definitions.

    Returns a plain dict from ``ChatCompletionResponse.model_dump()`` so callers
    stay decoupled from the SDK response type. For xAI only, XML ``<tool_call>``
    blocks embedded in ``message.content`` are normalised into structured
    ``tool_calls``.
    """
    provider = resolve_provider()
    client = get_llm_client()
    messages = [{"role": "system", "content": system_prompt}] + conversation_history

    # settings.LLM_MODEL is the Azure deployment name when LLM_PROVIDER == "azure".
    kwargs: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
    }
    if tool_definitions:
        kwargs["tools"] = tool_definitions
        kwargs["tool_choice"] = _tool_choice_value(force_tool)
    kwargs = _apply_reasoning_overrides(kwargs)

    sdk_response = client.chat.completions.create(**kwargs)
    response = ChatCompletionResponse.model_validate(sdk_response.model_dump())

    # Grok sometimes embeds tool calls as XML in content; Azure/OpenAI do not.
    if provider == "xai":
        response = _normalize_xml_tool_calls(response)

    return response.model_dump()
