from __future__ import annotations

from typing import Any, TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from .._base_client import AsyncHTTPClient, SyncHTTPClient
from .._exceptions import APIResponseValidationError, QCloudAIError
from .._uuid import normalize_uuid
from ..types.serverless import QueueCatalog, QueueDeployment, QueueDeploymentList, draft_name, trim_name, profile_id as check_profile
from .queue_runtime import ServerlessQueueRuntime, AsyncServerlessQueueRuntime

_PREFIX = "/serverless/queue"
_T = TypeVar("_T", bound=BaseModel)


def _parse(kind: type[_T], response: httpx.Response, *, envelope: bool = False) -> _T:
    try:
        value = response.json()
        if envelope:
            value = value.get("data") if isinstance(value, dict) else None
        return kind.model_validate(value)
    except (ValidationError, ValueError) as error:
        raise APIResponseValidationError("The API returned an invalid queue draft response") from error


def _query(org_id: str | None) -> str:
    return "" if org_id is None else "?org_id=" + normalize_uuid(org_id, "org_id")


def _body(name: str, profile_id: str, org_id: str | None, client_request_id: str | None) -> dict[str, Any]:
    if not isinstance(name, str):
        raise ValueError("A draft name is required")
    return {"name": draft_name(trim_name(name)), "profile_id": check_profile(profile_id),
            "client_request_id": normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id"),
            **({"org_id": normalize_uuid(org_id, "org_id")} if org_id is not None else {})}


def _created(response: httpx.Response, body: dict[str, Any]) -> QueueDeployment:
    result = _parse(QueueDeployment, response, envelope=True)
    if result.name != body["name"] or result.profile_id != body["profile_id"]:
        raise APIResponseValidationError("The API returned a different queue draft")
    return result


def _retrieved(response: httpx.Response, id: str) -> QueueDeployment:
    result = _parse(QueueDeployment, response, envelope=True)
    if result.id != id:
        raise APIResponseValidationError("The API returned a different queue draft")
    return result


class QueueDeployments:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def create(self, *, name: str, profile_id: str, org_id: str | None = None,
               client_request_id: str | None = None, timeout: float | None = None) -> QueueDeployment:
        body = _body(name, profile_id, org_id, client_request_id)
        try:
            return _created(self._client._request("POST", _PREFIX + "/deployments", body=body, max_retries=0, timeout=timeout), body)
        except QCloudAIError as error:
            error.client_request_id = body["client_request_id"]
            raise

    def list(self, *, org_id: str | None = None, timeout: float | None = None) -> QueueDeploymentList:
        return _parse(QueueDeploymentList, self._client._request("GET", _PREFIX + "/deployments" + _query(org_id), timeout=timeout))

    def retrieve(self, id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueDeployment:
        id = normalize_uuid(id, "deployment ID")
        return _retrieved(self._client._request("GET", _PREFIX + "/deployments/" + id + _query(org_id), timeout=timeout), id)


class AsyncQueueDeployments:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def create(self, *, name: str, profile_id: str, org_id: str | None = None,
                     client_request_id: str | None = None, timeout: float | None = None) -> QueueDeployment:
        body = _body(name, profile_id, org_id, client_request_id)
        try:
            return _created(await self._client._request("POST", _PREFIX + "/deployments", body=body, max_retries=0, timeout=timeout), body)
        except QCloudAIError as error:
            error.client_request_id = body["client_request_id"]
            raise

    async def list(self, *, org_id: str | None = None, timeout: float | None = None) -> QueueDeploymentList:
        return _parse(QueueDeploymentList, await self._client._request("GET", _PREFIX + "/deployments" + _query(org_id), timeout=timeout))

    async def retrieve(self, id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueDeployment:
        id = normalize_uuid(id, "deployment ID")
        return _retrieved(await self._client._request("GET", _PREFIX + "/deployments/" + id + _query(org_id), timeout=timeout), id)


class ServerlessQueue:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client
        self.deployments = QueueDeployments(client)
        self.runtime = ServerlessQueueRuntime(client)

    def catalog(self, *, org_id: str | None = None, timeout: float | None = None) -> QueueCatalog:
        return _parse(QueueCatalog, self._client._request("GET", _PREFIX + "/catalog" + _query(org_id), timeout=timeout))


class AsyncServerlessQueue:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client
        self.deployments = AsyncQueueDeployments(client)
        self.runtime = AsyncServerlessQueueRuntime(client)

    async def catalog(self, *, org_id: str | None = None, timeout: float | None = None) -> QueueCatalog:
        return _parse(QueueCatalog, await self._client._request("GET", _PREFIX + "/catalog" + _query(org_id), timeout=timeout))


class Serverless:
    def __init__(self, client: SyncHTTPClient) -> None:
        self.queue = ServerlessQueue(client)


class AsyncServerless:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self.queue = AsyncServerlessQueue(client)
