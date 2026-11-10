from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .._uuid import normalize_uuid
from .serverless import _PublicModel, QueueProfile, profile_id


def runtime_uuid(value: str, field: str) -> str:
    normalized = normalize_uuid(value, field)
    if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}", normalized):
        raise ValueError(f"{field} must be an RFC UUID with version 1 to 8")
    return normalized


def timestamp(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value):
        raise ValueError("Invalid queue runtime timestamp")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def bounded_text(value: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or "\0" in value or not minimum <= len(value.encode("utf-8")) <= maximum:
        raise ValueError("Invalid bounded queue text")
    return value


class QueueRuntimeCapabilities(_PublicModel):
    stage: Literal["inactive"]
    execution_available: Literal[False]
    billing_available: Literal[False]

    @field_validator("execution_available", "billing_available", mode="before")
    @classmethod
    def _disabled(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Queue runtime capabilities are inactive")
        return value


class QueueRuntimeQuote(_PublicModel):
    id: str
    client_request_id: str
    kind: Literal["endpoint", "job"]
    target_id: str
    expires_at: str
    currency: Literal["USD"]
    estimated_cost_usd: str
    funding_mode: Literal["metered"]
    is_spending_cap: Literal[False]

    @field_validator("id", "client_request_id", "target_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return runtime_uuid(value, "quote identity")

    _expiry = field_validator("expires_at")(timestamp)

    @field_validator("estimated_cost_usd")
    @classmethod
    def _cost(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,9})\.[0-9]{6}", value) or not 1 <= int(value.replace(".", "")) <= 9007199254740991:
            raise ValueError("Invalid quote estimate")
        return value

    @field_validator("is_spending_cap", mode="before")
    @classmethod
    def _not_cap(cls, value: object) -> object:
        if value is not False:
            raise ValueError("A quote estimate is not a spending cap")
        return value


class QueueRuntimeCursor(_PublicModel):
    created_at: str
    id: str

    _time = field_validator("created_at")(timestamp)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return runtime_uuid(value, "cursor ID")


class QueueRuntimeEndpoint(_PublicModel):
    id: str
    draft_id: str
    generation: int = Field(ge=1, le=2147483647)
    profile_id: str
    model: str
    state: Literal["prepared", "dispatch_unknown", "ready", "stopping", "deleted", "cancelled"]
    created_at: str
    deleted_at: str | None
    financial_exposure: Literal["held", "none"]
    requires_review: bool

    @field_validator("id", "draft_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return runtime_uuid(value, "resource ID")

    _profile = field_validator("profile_id")(profile_id)
    _model = field_validator("model")(QueueProfile._model)
    _created = field_validator("created_at")(timestamp)

    @field_validator("deleted_at")
    @classmethod
    def _deleted(cls, value: str | None) -> str | None:
        return None if value is None else timestamp(value)


class QueueRuntimeJob(_PublicModel):
    id: str
    endpoint_id: str
    state: Literal["prepared", "dispatch_unknown", "submitted", "completed", "failed", "cancelled", "expired"]
    created_at: str
    finished_at: str | None
    result_available: bool
    financial_exposure: Literal["held", "none"]
    requires_review: bool

    @field_validator("id", "endpoint_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return runtime_uuid(value, "resource ID")

    _created = field_validator("created_at")(timestamp)

    @field_validator("finished_at")
    @classmethod
    def _finished(cls, value: str | None) -> str | None:
        return None if value is None else timestamp(value)

    @model_validator(mode="after")
    def _consistent(self) -> QueueRuntimeJob:
        if self.result_available and self.state != "completed":
            raise ValueError("An unfinished queue job cannot expose a result")
        return self


def _page(items: list, cursor: QueueRuntimeCursor | None) -> None:
    if len({item.id for item in items}) != len(items):
        raise ValueError("Duplicate queue resource identity")
    if cursor is not None and (not items or cursor.id != items[-1].id or cursor.created_at != items[-1].created_at):
        raise ValueError("Queue page cursor does not match its final item")


class QueueRuntimeEndpointList(_PublicModel):
    items: list[QueueRuntimeEndpoint] = Field(max_length=50)
    next_cursor: QueueRuntimeCursor | None

    @model_validator(mode="after")
    def _consistent(self) -> QueueRuntimeEndpointList:
        _page(self.items, self.next_cursor)
        return self


class QueueRuntimeJobList(_PublicModel):
    items: list[QueueRuntimeJob] = Field(max_length=50)
    next_cursor: QueueRuntimeCursor | None

    @model_validator(mode="after")
    def _consistent(self) -> QueueRuntimeJobList:
        _page(self.items, self.next_cursor)
        return self


class QueueRuntimeStopResult(_PublicModel):
    released: bool
    financial_exposure: Literal["held", "none"]

    @model_validator(mode="after")
    def _consistent(self) -> QueueRuntimeStopResult:
        if self.released and self.financial_exposure != "none":
            raise ValueError("Released endpoint retains financial exposure")
        return self


class QueueRuntimeUsage(_PublicModel):
    input_tokens: int = Field(ge=0, le=32768)
    output_tokens: int = Field(ge=0, le=4096)
    total_tokens: int = Field(ge=0, le=32768)

    @model_validator(mode="after")
    def _consistent(self) -> QueueRuntimeUsage:
        if self.input_tokens + self.output_tokens != self.total_tokens:
            raise ValueError("Inconsistent queue token usage")
        return self


class QueueRuntimeTextResult(_PublicModel):
    text: str
    finish_reason: Literal["stop", "length"]
    usage: QueueRuntimeUsage

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return bounded_text(value, 0, 65536)


class QueueRuntimeResult(_PublicModel):
    available: bool
    result: QueueRuntimeTextResult | None = None

    @model_validator(mode="before")
    @classmethod
    def _pending(cls, value: object) -> object:
        # Pending responses must not expose any private result-shaped additions.
        if isinstance(value, dict) and value.get("available") is False:
            return {"available": False}
        return value

    @model_validator(mode="after")
    def _consistent(self) -> QueueRuntimeResult:
        if self.available and self.result is None:
            raise ValueError("Available queue result is missing")
        return self
