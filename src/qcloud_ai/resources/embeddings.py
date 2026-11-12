from __future__ import annotations

from typing import Any, Dict, List, Union

from .._response import parse_response
from .._base_client import SyncHTTPClient, AsyncHTTPClient
from ..types.embedding import CreateEmbeddingResponse


class Embeddings:
    """``client.embeddings`` — mirrors the OpenAI Embeddings API."""

    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        input: Union[str, List[str]],
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> CreateEmbeddingResponse:
        body: Dict[str, Any] = {"model": model, "input": input, **kwargs}

        response = self._client._request(
            "POST", "/embeddings", body=body, timeout=timeout, max_retries=max_retries
        )
        return parse_response(response, CreateEmbeddingResponse)


class AsyncEmbeddings:
    """``client.embeddings`` — async variant."""

    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        model: str,
        input: Union[str, List[str]],
        timeout: float | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> CreateEmbeddingResponse:
        body: Dict[str, Any] = {"model": model, "input": input, **kwargs}

        response = await self._client._request(
            "POST", "/embeddings", body=body, timeout=timeout, max_retries=max_retries
        )
        return parse_response(response, CreateEmbeddingResponse)
