from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Model(BaseModel):
    id: str = ""
    object: str = "model"
    created: int = 0
    owned_by: str = ""

    model_config = {"extra": "allow"}


class ModelList(BaseModel):
    object: str = "list"
    data: List[Model] = Field(default_factory=list)

    model_config = {"extra": "allow"}
