"""Unit tests for SSE streaming."""

from __future__ import annotations

import json
from typing import Iterator
from unittest.mock import MagicMock

import httpx

from qcloud_ai._streaming import Stream
from qcloud_ai.types.chat import ChatCompletionChunk


def _make_sse_response(events: list[dict]) -> httpx.Response:
    """Create a fake httpx.Response whose iter_lines yields SSE data."""
    lines: list[str] = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}")
        lines.append("")  # blank line between events
    lines.append("data: [DONE]")

    response = MagicMock(spec=httpx.Response)
    response.iter_lines.return_value = iter(lines)
    return response


CHUNK_1 = {
    "id": "chatcmpl-abc",
    "object": "chat.completion.chunk",
    "created": 1700000000,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "delta": {"role": "assistant", "content": "Hello"},
            "finish_reason": None,
        }
    ],
}

CHUNK_2 = {
    "id": "chatcmpl-abc",
    "object": "chat.completion.chunk",
    "created": 1700000000,
    "model": "gpt-4o-mini",
    "choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": None}],
}

CHUNK_DONE = {
    "id": "chatcmpl-abc",
    "object": "chat.completion.chunk",
    "created": 1700000000,
    "model": "gpt-4o-mini",
    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
}


class TestStream:
    def test_iterates_chunks(self) -> None:
        response = _make_sse_response([CHUNK_1, CHUNK_2, CHUNK_DONE])
        stream: Stream[ChatCompletionChunk] = Stream(response, cast=ChatCompletionChunk)

        chunks = list(stream)
        assert len(chunks) == 3
        assert isinstance(chunks[0], ChatCompletionChunk)
        assert chunks[0].choices[0].delta.content == "Hello"
        assert chunks[1].choices[0].delta.content == " world"
        assert chunks[2].choices[0].finish_reason == "stop"

    def test_context_manager(self) -> None:
        response = _make_sse_response([CHUNK_1])
        with Stream(response, cast=ChatCompletionChunk) as stream:
            chunks = list(stream)
            assert len(chunks) == 1
        response.close.assert_called_once()

    def test_empty_stream(self) -> None:
        response = _make_sse_response([])
        stream: Stream[ChatCompletionChunk] = Stream(response, cast=ChatCompletionChunk)
        assert list(stream) == []
