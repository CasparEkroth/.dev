from pydantic import BaseModel
from typing import Any, Literal


class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class Message(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str | None = None
    logprobs: Any = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: dict[str, Any] | None = None
    completion_tokens_details: dict[str, Any] | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: list[Choice]
    usage: Usage | None = None
    system_fingerprint: str | None = None
