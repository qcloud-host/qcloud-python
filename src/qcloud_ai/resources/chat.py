from __future__ import annotations

from typing import Any, Dict, List, Optional, Union, Literal, overload

from .._response import parse_response
from .._base_client import SyncHTTPClient, AsyncHTTPClient
from .._streaming import Stream, AsyncStream
from ..types.chat import ChatCompletion, ChatCompletionChunk


class ChatCompletions:
    """``client.chat.completions`` — mirrors the OpenAI Chat Completions API."""

    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    @overload
    def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: Literal[False] | None = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> ChatCompletion: ...

    @overload
    def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: Literal[True],
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Stream[ChatCompletionChunk]: ...

    @overload
    def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[ChatCompletion, Stream[ChatCompletionChunk]]: ...

    def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: Optional[bool] = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[ChatCompletion, Stream[ChatCompletionChunk]]:
        body: Dict[str, Any] = {"model": model, "messages": messages, **kwargs}
        if stream:
            body["stream"] = True

        response = self._client._request(
            "POST",
            "/chat/completions",
            body=body,
            stream=bool(stream),
            timeout=timeout,
            max_retries=max_retries,
        )

        if stream:
            return Stream(response, cast=ChatCompletionChunk)

        return parse_response(response, ChatCompletion)


class AsyncChatCompletions:
    """``client.chat.completions`` — async variant."""

    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    @overload
    async def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: Literal[False] | None = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> ChatCompletion: ...

    @overload
    async def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: Literal[True],
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> AsyncStream[ChatCompletionChunk]: ...

    @overload
    async def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[ChatCompletion, AsyncStream[ChatCompletionChunk]]: ...

    async def create(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: Optional[bool] = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[ChatCompletion, AsyncStream[ChatCompletionChunk]]:
        body: Dict[str, Any] = {"model": model, "messages": messages, **kwargs}
        if stream:
            body["stream"] = True

        response = await self._client._request(
            "POST",
            "/chat/completions",
            body=body,
            stream=bool(stream),
            timeout=timeout,
            max_retries=max_retries,
        )

        if stream:
            return AsyncStream(response, cast=ChatCompletionChunk)

        return parse_response(response, ChatCompletion)


class Chat:
    """``client.chat`` namespace — contains the ``completions`` sub-resource."""

    completions: ChatCompletions

    def __init__(self, client: SyncHTTPClient) -> None:
        self.completions = ChatCompletions(client)


class AsyncChat:
    """``client.chat`` namespace — async variant."""

    completions: AsyncChatCompletions

    def __init__(self, client: AsyncHTTPClient) -> None:
        self.completions = AsyncChatCompletions(client)
