from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field


class GenerationUploadedFile(BaseModel):
    """Private input reference; QCloud resolves it for an authorized model job."""
    id: str
    object: Literal["generation.file"]
    url: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: str
    expires_at: str


class GenerationModel(BaseModel):
    id: str
    object: Literal["generation.model"]
    display_name: str
    category: str
    description: str
    status: str
    available: bool
    transport: Literal["queue", "websocket", "webrtc", "unknown"]
    queued_available: bool
    schema_available: bool
    schema_format: Literal["openapi", "asyncapi"] | None = None
    # None preserves compatibility with older snapshots; it is not proof of freshness.
    reference_status: Literal["current", "retained", "unavailable"] | None = None
    reference_stale: bool | None = None
    reference_checked_at: str | None = None
    reference_updated_at: str | None = None
    reference_issue: Literal["upstream_reference_unavailable"] | None = None
    schema_complete: bool = False
    schema_issues: list[dict[str, Any]] = []
    license: dict[str, Any] | None
    updated_at: str
    pricing: dict[str, Any] | None = None
    # Additional admission restrictions may be narrower than the model schema.
    admission_policy: dict[str, Any] | None = None
    availability_reason: str | None = None
    schema_url: str
    model_config = {"extra": "allow"}


class GenerationModelList(BaseModel):
    object: Literal["list"]
    data: list[GenerationModel]
    has_more: bool
    next_cursor: str | None
    # Includes degraded and quarantined_count on servers with reference provenance.
    catalog: dict[str, Any]
    model_config = {"extra": "allow"}


GenerationJobStatus = Literal[
    "queued", "submitting", "running", "succeeded", "failed", "cancelled", "review"
]


class GenerationBilling(BaseModel):
    mode: Literal["metered"]
    status: Literal["pending", "settled", "review"]
    currency: Literal["USD"]
    markup_multiplier: float
    cost_usd: float | None
    model_config = {"extra": "allow"}


class GenerationJob(BaseModel):
    object: Literal["generation.job"]
    id: str
    model: str
    status: GenerationJobStatus
    created_at: str
    updated_at: str
    completed_at: str | None
    deadline_at: str
    cancel_requested: bool
    error: dict[str, Any] | None
    billing: GenerationBilling
    result_url: str | None
    license: dict[str, Any] | None = None
    model_config = {"extra": "allow"}


OutputT = TypeVar("OutputT")


class GenerationResult(BaseModel, Generic[OutputT]):
    job_id: str
    data: OutputT
    billing: GenerationBilling
    model_config = {"extra": "allow"}


class GenerationPendingResult(BaseModel):
    data: GenerationJob
    model_config = {"extra": "allow"}


class GenerationSubscription(BaseModel, Generic[OutputT]):
    job: GenerationJob
    result: GenerationResult[OutputT]


class GenerationSession(BaseModel):
    object: Literal["generation.session"]
    id: str
    model: str
    transport: Literal["websocket", "webrtc"]
    status: Literal["created", "connecting", "active", "closing", "closed", "review"]
    created_at: str
    updated_at: str
    connected_at: str | None
    completed_at: str | None
    deadline_at: str | None
    expires_at: str
    max_duration_seconds: int
    close_requested: bool
    error: dict[str, Any] | None
    billing: GenerationBilling
    license: dict[str, Any] | None
    model_config = {"extra": "allow"}


class GenerationWebSocketConnection(BaseModel):
    transport: Literal["websocket"]
    signaling: Literal["websocket"] = "websocket"
    session_id: str | None = None
    websocket_url: str
    token: str = Field(repr=False)
    expires_at: str
    subprotocols: list[str] = Field(repr=False)
    encoding: Literal["msgpack", "json"]
    model_config = {"extra": "allow"}


class GenerationWebRTCConnection(BaseModel):
    transport: Literal["webrtc"]
    signaling: Literal["sse"] = "sse"
    session_id: str | None = None
    url: str
    token: str = Field(repr=False)
    expires_at: str
    model_config = {"extra": "allow"}


class GenerationWebRTCSignalingConnection(BaseModel):
    """A model-specific signaling socket paired with a separate media peer."""

    transport: Literal["webrtc"]
    signaling: Literal["websocket"]
    protocol: Literal["rtc-signaling-v1"]
    session_id: str | None = None
    websocket_url: str
    token: str = Field(repr=False)
    expires_at: str
    subprotocols: list[str] = Field(repr=False)
    encoding: Literal["msgpack"]
    model_config = {"extra": "allow"}


GenerationSessionConnection = (
    GenerationWebSocketConnection
    | GenerationWebRTCConnection
    | GenerationWebRTCSignalingConnection
)


class GenerationSessionEvent(BaseModel):
    event: Literal["answer", "closed"]
    data: dict[str, Any]
