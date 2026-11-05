from __future__ import annotations

from typing import Any, Dict, List, Union

from .._base_client import SyncHTTPClient, AsyncHTTPClient
from .._exceptions import _raise_for_status
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
        **kwargs: Any,
    ) -> CreateEmbeddingResponse:
        body: Dict[str, Any] = {"model": model, "input": input, **kwargs}

        response = self._client._request("POST", "/embeddings", body=body)
        data = response.json()
        _raise_for_status(response.status_code, data)
        return CreateEmbeddingResponse(**data)


class AsyncEmbeddings:
    """``client.embeddings`` — async variant."""

    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        model: str,
        input: Union[str, List[str]],
        **kwargs: Any,
    ) -> CreateEmbeddingResponse:
        body: Dict[str, Any] = {"model": model, "input": input, **kwargs}

        response = await self._client._request("POST", "/embeddings", body=body)
        data = response.json()
        _raise_for_status(response.status_code, data)
        return CreateEmbeddingResponse(**data)
