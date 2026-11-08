from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .._uuid import normalize_uuid


_TRIM = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def trim_name(value: str) -> str:
    return value.strip(_TRIM)


def profile_name(value: str) -> str:
    # JavaScript's public API counts UTF-16 code units, not Unicode code points.
    if (not isinstance(value, str) or value != trim_name(value)
            or not 2 <= len(value.encode("utf-16-le")) // 2 <= 80):
        raise ValueError("Invalid queue profile name")
    return value


def draft_name(value: str) -> str:
    profile_name(value)
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Invalid queue draft name")
    return value


def profile_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", value):
        raise ValueError("Invalid catalog profile_id")
    return value


class _PublicModel(BaseModel):
    # Validate known fields without returning private/provider additions.
    model_config = {"strict": True, "extra": "ignore"}


class QueueLimits(_PublicModel):
    max_workers: Literal[1]
    idle_timeout_seconds: int = Field(ge=1, le=3600)
    execution_timeout_seconds: int = Field(ge=5, le=3600)

    @field_validator("max_workers", mode="before")
    @classmethod
    def _one_worker(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Invalid worker limit")
        return value


class QueueProfile(_PublicModel):
    id: str
    name: str
    model: str
    gpu_memory_gb: int = Field(ge=8, le=192)
    disk_gb: int = Field(ge=10, le=512)
    limits: QueueLimits
    pricing: None

    _id = field_validator("id")(profile_id)
    _name = field_validator("name")(profile_name)

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise ValueError("Invalid model identity")
        return value


class QueueCatalog(_PublicModel):
    stage: Literal["draft_preview"]
    runtime_available: Literal[False]
    creation_available: bool
    profiles: list[QueueProfile] = Field(max_length=16)
    unsupported: list[str] = Field(max_length=32)

    @field_validator("runtime_available", mode="before")
    @classmethod
    def _disabled(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Draft catalog cannot enable runtime")
        return value

    @field_validator("unsupported")
    @classmethod
    def _unsupported(cls, value: list[str]) -> list[str]:
        if any(len(item) > 80 for item in value):
            raise ValueError("Invalid capability label")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> QueueCatalog:
        if self.creation_available != bool(self.profiles) or len({p.id for p in self.profiles}) != len(self.profiles):
            raise ValueError("Inconsistent draft catalog")
        return self


class QueueDeployment(_PublicModel):
    """Saved planning record. It does not represent a running endpoint."""
    id: str
    name: str
    status: Literal["draft"]
    profile_id: str
    profile_name: str
    model: str
    created_at: str
    updated_at: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return normalize_uuid(value, "deployment ID")

    _name = field_validator("name")(draft_name)
    _profile_name = field_validator("profile_name")(profile_name)
    _profile = field_validator("profile_id")(profile_id)

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        return QueueProfile._model(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamp(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", value):
            raise ValueError("Invalid draft timestamp")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class QueueDeploymentList(_PublicModel):
    data: list[QueueDeployment] = Field(max_length=100)

    @model_validator(mode="after")
    def _unique(self) -> QueueDeploymentList:
        if len({draft.id for draft in self.data}) != len(self.data):
            raise ValueError("Duplicate deployment identity")
        return self
