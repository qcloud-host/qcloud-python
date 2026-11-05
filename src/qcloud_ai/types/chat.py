from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ChatCompletionMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[Any]] = None
    function_call: Optional[Any] = None

    model_config = {"extra": "allow"}


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage = Field(default_factory=ChatCompletionMessage)
    finish_reason: Optional[str] = None

    model_config = {"extra": "allow"}


class CompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    model_config = {"extra": "allow"}


class ChatCompletion(BaseModel):
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: List[ChatCompletionChoice] = Field(default_factory=list)
    usage: Optional[CompletionUsage] = None
    system_fingerprint: Optional[str] = None

    model_config = {"extra": "allow"}


class ChatCompletionChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: Optional[List[Any]] = None
    function_call: Optional[Any] = None

    model_config = {"extra": "allow"}


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionChunkDelta = Field(default_factory=ChatCompletionChunkDelta)
    finish_reason: Optional[str] = None

    model_config = {"extra": "allow"}


class ChatCompletionChunk(BaseModel):
    usage: Optional[CompletionUsage] = None
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: List[ChatCompletionChunkChoice] = Field(default_factory=list)
    system_fingerprint: Optional[str] = None

    model_config = {"extra": "allow"}
