from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class MessageUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    model_config = {"extra": "allow"}


class MessageContentBlock(BaseModel):
    """A ``text`` or ``tool_use`` block. Other fields are preserved as extras."""

    type: str
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Any] = None

    model_config = {"extra": "allow"}


class Message(BaseModel):
    """Response of ``POST /v1/messages`` (Anthropic Messages format)."""

    id: str = ""
    type: str = "message"
    role: str = "assistant"
    model: str = ""
    content: List[MessageContentBlock] = Field(default_factory=list)
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: Optional[MessageUsage] = None

    model_config = {"extra": "allow"}

    @property
    def text(self) -> str:
        """Concatenated text of all ``text`` content blocks."""
        return "".join(block.text or "" for block in self.content if block.type == "text")


class MessageStreamEvent(BaseModel):
    """One named Messages SSE event such as ``message_start``,
    ``content_block_delta``, ``message_delta`` or ``message_stop``.

    Event-specific fields (``message``, ``index``, ``delta``,
    ``content_block``, ``usage``) are available as attributes.
    """

    type: str

    model_config = {"extra": "allow"}
