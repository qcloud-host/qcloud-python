from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Model(BaseModel):
    id: str = ""
    object: str = "model"
    created: int = 0
    owned_by: str = ""
    display_name: Optional[str] = None
    provider: Optional[str] = None
    provider_model_id: Optional[str] = None
    context_length: Optional[int] = None
    max_output_tokens: Optional[int] = None
    modality: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    pricing: Optional[dict[str, float]] = None
    catalog_verified_at: Optional[str] = None
    stale: Optional[bool] = None

    model_config = {"extra": "allow"}


class ModelList(BaseModel):
    object: str = "list"
    data: List[Model] = Field(default_factory=list)
    catalog: Optional[dict] = None

    model_config = {"extra": "allow"}
