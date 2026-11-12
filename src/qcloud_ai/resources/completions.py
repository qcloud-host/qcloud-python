from __future__ import annotations

from typing import Any, Dict, Optional, Union, Literal, overload

from .._response import parse_response
from .._base_client import SyncHTTPClient, AsyncHTTPClient
from .._streaming import Stream, AsyncStream
from ..types.completion import Completion, CompletionChunk


class Completions:
    """``client.completions`` — mirrors the OpenAI legacy Completions API."""

    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    @overload
    def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: Literal[False] | None = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Completion: ...

    @overload
    def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: Literal[True],
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Stream[CompletionChunk]: ...

    @overload
    def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: bool = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[Completion, Stream[CompletionChunk]]: ...

    def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: Optional[bool] = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[Completion, Stream[CompletionChunk]]:
        body: Dict[str, Any] = {"model": model, "prompt": prompt, **kwargs}
        if stream:
            body["stream"] = True

        response = self._client._request(
            "POST",
            "/completions",
            body=body,
            stream=bool(stream),
            timeout=timeout,
            max_retries=max_retries,
        )

        if stream:
            return Stream(response, cast=CompletionChunk)

        return parse_response(response, Completion)


class AsyncCompletions:
    """``client.completions`` — async variant."""

    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    @overload
    async def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: Literal[False] | None = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Completion: ...

    @overload
    async def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: Literal[True],
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> AsyncStream[CompletionChunk]: ...

    @overload
    async def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: bool = ...,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[Completion, AsyncStream[CompletionChunk]]: ...

    async def create(
        self,
        *,
        model: str,
        prompt: str,
        stream: Optional[bool] = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Union[Completion, AsyncStream[CompletionChunk]]:
        body: Dict[str, Any] = {"model": model, "prompt": prompt, **kwargs}
        if stream:
            body["stream"] = True

        response = await self._client._request(
            "POST",
            "/completions",
            body=body,
            stream=bool(stream),
            timeout=timeout,
            max_retries=max_retries,
        )

        if stream:
            return AsyncStream(response, cast=CompletionChunk)

        return parse_response(response, Completion)
