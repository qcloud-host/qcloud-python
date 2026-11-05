from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Embedding(BaseModel):
    object: str = "embedding"
    index: int = 0
    embedding: List[float] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class EmbeddingUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0

    model_config = {"extra": "allow"}


class CreateEmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[Embedding] = Field(default_factory=list)
    model: str = ""
    usage: Optional[EmbeddingUsage] = None

    model_config = {"extra": "allow"}
