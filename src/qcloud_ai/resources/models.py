from __future__ import annotations

from urllib.parse import quote

from .._base_client import SyncHTTPClient, AsyncHTTPClient
from .._response import parse_response
from ..types.model import Model, ModelList


class Models:
    """``client.models`` — mirrors the OpenAI Models API."""

    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def list(
        self, *, timeout: float | None = None, max_retries: int | None = None
    ) -> ModelList:
        response = self._client._request(
            "GET", "/models", timeout=timeout, max_retries=max_retries
        )
        return parse_response(response, ModelList)

    def retrieve(
        self,
        model: str,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Model:
        response = self._client._request(
            "GET",
            f"/models/{quote(model, safe='')}",
            timeout=timeout,
            max_retries=max_retries,
        )
        return parse_response(response, Model)


class AsyncModels:
    """``client.models`` — async variant."""

    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def list(
        self, *, timeout: float | None = None, max_retries: int | None = None
    ) -> ModelList:
        response = await self._client._request(
            "GET", "/models", timeout=timeout, max_retries=max_retries
        )
        return parse_response(response, ModelList)

    async def retrieve(
        self,
        model: str,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Model:
        response = await self._client._request(
            "GET",
            f"/models/{quote(model, safe='')}",
            timeout=timeout,
            max_retries=max_retries,
        )
        return parse_response(response, Model)
