from __future__ import annotations

from urllib.parse import quote

from .._base_client import SyncHTTPClient, AsyncHTTPClient
from .._exceptions import _raise_for_status
from ..types.model import Model, ModelList


class Models:
    """``client.models`` — mirrors the OpenAI Models API."""

    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def list(self) -> ModelList:
        response = self._client._request("GET", "/models")
        data = response.json()
        _raise_for_status(response.status_code, data)
        return ModelList(**data)

    def retrieve(self, model: str) -> Model:
        response = self._client._request("GET", f"/models/{quote(model, safe='')}")
        data = response.json()
        _raise_for_status(response.status_code, data)
        return Model(**data)


class AsyncModels:
    """``client.models`` — async variant."""

    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def list(self) -> ModelList:
        response = await self._client._request("GET", "/models")
        data = response.json()
        _raise_for_status(response.status_code, data)
        return ModelList(**data)

    async def retrieve(self, model: str) -> Model:
        response = await self._client._request(
            "GET", f"/models/{quote(model, safe='')}"
        )
        data = response.json()
        _raise_for_status(response.status_code, data)
        return Model(**data)
