"""Tests for shared.llm_client (OpenAI SDK + Azure support)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from shared import llm_client
from shared.llm_client import (
    _apply_reasoning_overrides,
    _tool_choice_value,
    call_llm,
    call_llm_with_tools,
    get_context_window,
    get_llm_client,
    reset_llm_client,
    resolve_provider,
)
from shared.llm_types import ChatCompletionResponse

SAMPLE_TOOL = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": "Run a shell command",
        "parameters": {"type": "object", "properties": {}},
    },
}

STRUCTURED_TOOL_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 1_700_000_000,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": '{"command": "ls"}',
                        },
                    }
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    },
}

XML_TOOL_CONTENT = (
    "Say something first.\n"
    '<tool_call>{"name": "shell", "arguments": {"command": "pwd"}}</tool_call>'
)

XML_TOOL_RESPONSE = {
    "id": "chatcmpl-xml",
    "object": "chat.completion",
    "created": 1_700_000_001,
    "model": "grok-4.5",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": XML_TOOL_CONTENT,
                "tool_calls": None,
            },
        }
    ],
    "usage": {
        "prompt_tokens": 8,
        "completion_tokens": 12,
        "total_tokens": 20,
    },
}


@pytest.fixture(autouse=True)
def _reset_client_cache():
    reset_llm_client()
    yield
    reset_llm_client()


def _sdk_response(payload: dict) -> MagicMock:
    """Build a MagicMock that looks like an OpenAI SDK ChatCompletion."""
    mock = MagicMock()
    mock.model_dump.return_value = payload
    # call_llm reads .choices[0].message.content directly off the SDK object.
    choice = MagicMock()
    choice.message.content = payload["choices"][0]["message"].get("content")
    mock.choices = [choice]
    return mock


# ---------------------------------------------------------------------------
# Provider inference / override
# ---------------------------------------------------------------------------


def test_resolve_provider_infers_xai_from_base_url():
    assert (
        resolve_provider(provider=None, base_url="https://api.x.ai/v1/chat/completions")
        == "xai"
    )


def test_resolve_provider_infers_azure_from_base_url():
    assert (
        resolve_provider(
            provider=None,
            base_url="https://my-resource.openai.azure.com/",
        )
        == "azure"
    )


def test_resolve_provider_infers_openai_from_base_url():
    assert (
        resolve_provider(provider=None, base_url="https://api.openai.com/v1")
        == "openai"
    )


def test_resolve_provider_explicit_override_wins():
    # Even with an xAI URL, an explicit provider must win.
    assert resolve_provider(provider="azure", base_url="https://api.x.ai/v1") == "azure"
    assert (
        resolve_provider(provider="OpenAI", base_url="https://api.x.ai/v1") == "openai"
    )


def test_resolve_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        resolve_provider(provider="anthropic")


def test_resolve_provider_reads_settings(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", None)
    monkeypatch.setattr(
        llm_client.settings, "LLM_BASE_URL", "https://foo.openai.azure.com/"
    )
    assert resolve_provider() == "azure"


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def test_get_llm_client_azure_uses_deployment_settings(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(
        llm_client.settings,
        "LLM_BASE_URL",
        "https://my-resource.openai.azure.com/",
    )
    monkeypatch.setattr(llm_client.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client.settings, "AZURE_API_VERSION", "2024-10-21")

    with patch("shared.llm_client.AzureOpenAI") as azure_cls:
        azure_cls.return_value = MagicMock(name="azure_client")
        client = get_llm_client()
        azure_cls.assert_called_once()
        kwargs = azure_cls.call_args.kwargs
        assert kwargs["azure_endpoint"] == "https://my-resource.openai.azure.com"
        assert kwargs["api_key"] == "test-key"
        assert kwargs["api_version"] == "2024-10-21"
        assert kwargs["max_retries"] == 3
        assert client is azure_cls.return_value


def test_get_llm_client_openai_compatible(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "xai")
    monkeypatch.setattr(
        llm_client.settings, "LLM_BASE_URL", "https://api.x.ai/v1/chat/completions"
    )
    monkeypatch.setattr(llm_client.settings, "LLM_API_KEY", "xai-key")

    with patch("shared.llm_client.OpenAI") as openai_cls:
        openai_cls.return_value = MagicMock(name="openai_client")
        client = get_llm_client()
        kwargs = openai_cls.call_args.kwargs
        assert kwargs["base_url"] == "https://api.x.ai/v1"
        assert kwargs["api_key"] == "xai-key"
        assert kwargs["max_retries"] == 3
        assert client is openai_cls.return_value


def test_get_llm_client_is_cached(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(
        llm_client.settings, "LLM_BASE_URL", "https://api.openai.com/v1"
    )
    monkeypatch.setattr(llm_client.settings, "LLM_API_KEY", "k")

    with patch("shared.llm_client.OpenAI") as openai_cls:
        openai_cls.return_value = MagicMock(name="c")
        a = get_llm_client()
        b = get_llm_client()
        assert a is b
        assert openai_cls.call_count == 1


def test_reset_llm_client_clears_cache(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(
        llm_client.settings, "LLM_BASE_URL", "https://api.openai.com/v1"
    )
    monkeypatch.setattr(llm_client.settings, "LLM_API_KEY", "k")

    with patch("shared.llm_client.OpenAI") as openai_cls:
        openai_cls.side_effect = [MagicMock(name="c1"), MagicMock(name="c2")]
        a = get_llm_client()
        reset_llm_client()
        b = get_llm_client()
        assert a is not b
        assert openai_cls.call_count == 2


# ---------------------------------------------------------------------------
# force_tool / tool_choice
# ---------------------------------------------------------------------------


def test_tool_choice_required_when_forced():
    assert _tool_choice_value(True) == "required"


def test_tool_choice_auto_when_not_forced():
    assert _tool_choice_value(False) == "auto"


def test_call_llm_with_tools_force_tool_xai(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "xai")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "grok-4.5")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _sdk_response(
        STRUCTURED_TOOL_RESPONSE
    )
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    call_llm_with_tools(
        "sys",
        [{"role": "user", "content": "hi"}],
        [SAMPLE_TOOL],
        force_tool=True,
    )
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["tool_choice"] == "required"
    assert kwargs["model"] == "grok-4.5"


def test_call_llm_with_tools_force_tool_azure(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "my-gpt-deployment")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _sdk_response(
        STRUCTURED_TOOL_RESPONSE
    )
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    call_llm_with_tools(
        "sys",
        [{"role": "user", "content": "hi"}],
        [SAMPLE_TOOL],
        force_tool=True,
    )
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "my-gpt-deployment"  # deployment name
    # Must be "required" (any tool), not a single named function — otherwise
    # multi-tool agents can only call whichever tool is listed first.
    assert kwargs["tool_choice"] == "required"


def test_call_llm_with_tools_model_override(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "xai")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "configured-default")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _sdk_response(
        STRUCTURED_TOOL_RESPONSE
    )
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    call_llm_with_tools(
        "sys",
        [{"role": "user", "content": "hi"}],
        [SAMPLE_TOOL],
        model="agent-pinned-model",
    )
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "agent-pinned-model"


def test_call_llm_with_tools_falls_back_to_configured_model(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "xai")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "configured-default")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _sdk_response(
        STRUCTURED_TOOL_RESPONSE
    )
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    call_llm_with_tools("sys", [{"role": "user", "content": "hi"}], [SAMPLE_TOOL])
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "configured-default"


# ---------------------------------------------------------------------------
# Reasoning-model param translation
# ---------------------------------------------------------------------------


def test_reasoning_model_translates_max_tokens_and_drops_sampling(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", True)
    out = _apply_reasoning_overrides(
        {
            "model": "o1",
            "max_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.2,
            "messages": [],
        }
    )
    assert "max_tokens" not in out
    assert out["max_completion_tokens"] == 100
    assert "temperature" not in out
    assert "top_p" not in out
    assert "presence_penalty" not in out
    assert "frequency_penalty" not in out
    assert out["model"] == "o1"


def test_reasoning_model_flag_off_is_noop(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)
    original = {"max_tokens": 50, "temperature": 0.5}
    assert _apply_reasoning_overrides(original) == original


def test_call_llm_applies_reasoning_overrides(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", True)
    kwargs = _apply_reasoning_overrides(
        {
            "model": "o3-mini",
            "max_tokens": 32,
            "temperature": 0.2,
            "messages": [],
        }
    )
    assert kwargs["max_completion_tokens"] == 32
    assert "temperature" not in kwargs


# ---------------------------------------------------------------------------
# Structured tool_calls round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["xai", "azure", "openai"])
def test_structured_tool_calls_round_trip(monkeypatch, provider):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", provider)
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "dep-or-model")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _sdk_response(
        STRUCTURED_TOOL_RESPONSE
    )
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    result = call_llm_with_tools(
        "sys", [{"role": "user", "content": "hi"}], [SAMPLE_TOOL]
    )
    validated = ChatCompletionResponse.model_validate(result)
    assert validated.choices[0].message.tool_calls is not None
    assert validated.choices[0].message.tool_calls[0].function.name == "shell"
    assert validated.choices[0].message.content is None
    assert (
        result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "shell"
    )


# ---------------------------------------------------------------------------
# XML tool-call fallback (xAI only)
# ---------------------------------------------------------------------------


def test_xai_xml_tool_call_is_normalised(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "xai")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "grok-4.5")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _sdk_response(XML_TOOL_RESPONSE)
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    result = call_llm_with_tools(
        "sys", [{"role": "user", "content": "hi"}], [SAMPLE_TOOL]
    )
    message = result["choices"][0]["message"]
    assert message["content"] is None
    assert message["tool_calls"] is not None
    assert message["tool_calls"][0]["function"]["name"] == "shell"
    args = json.loads(message["tool_calls"][0]["function"]["arguments"])
    assert args["command"] == "pwd"


def test_azure_xml_tool_call_is_left_alone(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "my-deployment")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _sdk_response(XML_TOOL_RESPONSE)
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    result = call_llm_with_tools(
        "sys", [{"role": "user", "content": "hi"}], [SAMPLE_TOOL]
    )
    message = result["choices"][0]["message"]
    # Azure path must NOT promote XML content into tool_calls.
    assert message["tool_calls"] is None
    assert message["content"] == XML_TOOL_CONTENT


# ---------------------------------------------------------------------------
# get_context_window
# ---------------------------------------------------------------------------


def test_get_context_window_azure_has_no_lookup(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "azure")
    # Azure exposes no context-window API -> always None (must not raise).
    result = get_context_window(
        "https://my-resource.openai.azure.com/", "key", "custom-deploy-42"
    )
    assert result is None


def test_get_context_window_explicit_provider_overrides_url_inference(monkeypatch):
    # A custom domain that wouldn't infer as "azure" from the URL alone.
    result = get_context_window(
        "https://my-custom-gateway.example.com/",
        "key",
        "custom-deploy-42",
        provider="azure",
    )
    assert result is None  # still no lookup, but resolves without raising


def test_get_context_window_xai_listing_failure_returns_none(monkeypatch):
    class _Boom:
        def __enter__(self):
            raise llm_client.httpx.ConnectError("no network")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(llm_client.httpx, "Client", lambda **kw: _Boom())
    result = get_context_window("https://api.x.ai/v1", "key", "grok-4.5")
    assert result is None


def test_call_llm_returns_content(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "gpt-4o")
    monkeypatch.setattr(llm_client.settings, "LLM_REASONING_MODEL", False)

    mock_client = MagicMock()
    payload = {
        "id": "c",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello world"},
                "finish_reason": "stop",
            }
        ],
    }
    mock_client.chat.completions.create.return_value = _sdk_response(payload)
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: mock_client)

    assert call_llm("ping") == "hello world"
