from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union, overload

from .._base_client import AsyncHTTPClient, SyncHTTPClient
from .._streaming import AsyncStream, Stream
from ..types.message import Message, MessageStreamEvent

ANTHROPIC_VERSION = "2023-06-01"
_HEADERS = {"anthropic-version": ANTHROPIC_VERSION}


def _is_stop(event: MessageStreamEvent) -> bool:
    return event.type == "message_stop"


def _body(
    model: str,
    max_tokens: int,
    messages: List[Dict[str, Any]],
    stream: Optional[bool],
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        **kwargs,
    }
    if stream:
        body["stream"] = True
    return body


class Messages:
    """``client.messages`` — the supported subset of the Anthropic Messages API.

    QCloud bridges Messages requests to its verified chat catalog. Thinking,
    prompt caching, beta headers, documents, server tools, ``top_k`` and
    non-empty ``stop_sequences`` are rejected with ``BadRequestError`` before
    any provider dispatch. Exact token counting is not available.
    """

    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    @overload
    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: Literal[False] | None = ...,
        **kwargs: Any,
    ) -> Message: ...

    @overload
    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: Literal[True],
        **kwargs: Any,
    ) -> Stream[MessageStreamEvent]: ...

    @overload
    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: bool = ...,
        **kwargs: Any,
    ) -> Union[Message, Stream[MessageStreamEvent]]: ...

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[Message, Stream[MessageStreamEvent]]:
        response = self._client._request(
            "POST",
            "/messages",
            body=_body(model, max_tokens, messages, stream, kwargs),
            stream=bool(stream),
            headers=_HEADERS,
        )
        if stream:
            return Stream(response, cast=MessageStreamEvent, terminal=_is_stop)
        return Message(**response.json())


class AsyncMessages:
    """``client.messages`` — async variant."""

    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    @overload
    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: Literal[False] | None = ...,
        **kwargs: Any,
    ) -> Message: ...

    @overload
    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: Literal[True],
        **kwargs: Any,
    ) -> AsyncStream[MessageStreamEvent]: ...

    @overload
    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: bool = ...,
        **kwargs: Any,
    ) -> Union[Message, AsyncStream[MessageStreamEvent]]: ...

    async def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: List[Dict[str, Any]],
        stream: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[Message, AsyncStream[MessageStreamEvent]]:
        response = await self._client._request(
            "POST",
            "/messages",
            body=_body(model, max_tokens, messages, stream, kwargs),
            stream=bool(stream),
            headers=_HEADERS,
        )
        if stream:
            return AsyncStream(response, cast=MessageStreamEvent, terminal=_is_stop)
        return Message(**response.json())
