from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from .chat import CompletionUsage


class CompletionChoice(BaseModel):
    index: int = 0
    text: str = ""
    finish_reason: Optional[str] = None
    logprobs: Optional[Any] = None

    model_config = {"extra": "allow"}


class Completion(BaseModel):
    id: str = ""
    object: str = "text_completion"
    created: int = 0
    model: str = ""
    choices: List[CompletionChoice] = Field(default_factory=list)
    usage: Optional[CompletionUsage] = None
    system_fingerprint: Optional[str] = None

    model_config = {"extra": "allow"}


class CompletionChunkChoice(BaseModel):
    index: int = 0
    text: str = ""
    finish_reason: Optional[str] = None
    logprobs: Optional[Any] = None

    model_config = {"extra": "allow"}


class CompletionChunk(BaseModel):
    id: str = ""
    object: str = "text_completion"
    created: int = 0
    model: str = ""
    choices: List[CompletionChunkChoice] = Field(default_factory=list)
    system_fingerprint: Optional[str] = None

    model_config = {"extra": "allow"}
