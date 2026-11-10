from __future__ import annotations

from typing import Any, TypeVar
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from .._base_client import AsyncHTTPClient, SyncHTTPClient
from .._exceptions import APIResponseValidationError
from ..types.queue_runtime import runtime_uuid as normalize_uuid
from ..types.queue_runtime import (QueueRuntimeCapabilities, QueueRuntimeEndpoint, QueueRuntimeEndpointList,
                                  QueueRuntimeJob, QueueRuntimeJobList, QueueRuntimeResult, QueueRuntimeStopResult, QueueRuntimeQuote,
                                  bounded_text, timestamp)

_PREFIX = "/serverless/queue/runtime"
_T = TypeVar("_T", bound=BaseModel)


def _invalid() -> APIResponseValidationError:
    return APIResponseValidationError("The API returned an invalid queue runtime response")


def _parse(kind: type[_T], response: httpx.Response, *, envelope: bool = False) -> _T:
    try:
        value = response.json()
        if envelope:
            value = value.get("data") if isinstance(value, dict) else None
        return kind.model_validate(value)
    except (ValidationError, ValueError) as error:
        raise _invalid() from error


def _query(org_id: str | None, limit: int | None = None, after_created_at: str | None = None,
           after_id: str | None = None) -> str:
    values: dict[str, Any] = {}
    if org_id is not None:
        values["org_id"] = normalize_uuid(org_id, "org_id")
    if limit is not None:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer from 1 to 50")
        values["limit"] = limit
    if (after_created_at is None) != (after_id is None):
        raise ValueError("Both cursor fields are required")
    if after_created_at is not None:
        values["after_created_at"] = timestamp(after_created_at)
        values["after_id"] = normalize_uuid(after_id, "after_id")
    return "?" + urlencode(values) if values else ""


def _body(quote_id: str | None, request_id: str, org_id: str | None, input: dict[str, Any] | None = None,
          *, is_job: bool = False, is_quote: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {"client_request_id": request_id}
    if not is_quote:
        body["quote_id"] = normalize_uuid(quote_id, "quote_id")
    if org_id is not None:
        body["org_id"] = normalize_uuid(org_id, "org_id")
    if is_job:
        if not isinstance(input, dict) or set(input) != {"prompt", "max_tokens"}:
            raise ValueError("Invalid queue text input fields")
        prompt = bounded_text(input["prompt"], 1, 16384)
        tokens = input["max_tokens"]
        if type(tokens) is not int or not 1 <= tokens <= 4096:
            raise ValueError("max_tokens must be an integer from 1 to 4096")
        body["input"] = {"prompt": prompt, "max_tokens": tokens}
    return body


def _identity(error: Exception, request_id: str) -> None:
    # Validation, transport and API failures retain the same replay identity.
    try:
        error.client_request_id = request_id  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        pass


def _endpoint(response: httpx.Response, expected: str | None = None, draft: str | None = None) -> QueueRuntimeEndpoint:
    result = _parse(QueueRuntimeEndpoint, response, envelope=True)
    if (expected is not None and result.id != expected) or (draft is not None and result.draft_id != draft):
        raise _invalid()
    return result


def _quote(response: httpx.Response, kind: str, target: str, request_id: str) -> QueueRuntimeQuote:
    result = _parse(QueueRuntimeQuote, response, envelope=True)
    if result.kind != kind or result.target_id != target or result.client_request_id != request_id:
        raise _invalid()
    return result


def _job(response: httpx.Response, endpoint: str, expected: str | None = None) -> QueueRuntimeJob:
    result = _parse(QueueRuntimeJob, response, envelope=True)
    if result.endpoint_id != endpoint or (expected is not None and result.id != expected):
        raise _invalid()
    return result


def _page(kind: type[_T], response: httpx.Response, limit: int | None, endpoint: str | None = None) -> _T:
    result = _parse(kind, response)
    if len(result.items) > (20 if limit is None else limit):  # type: ignore[attr-defined]
        raise _invalid()
    if endpoint is not None and any(item.endpoint_id != endpoint for item in result.items):  # type: ignore[attr-defined]
        raise _invalid()
    return result


class QueueRuntimeEndpoints:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def quote(self, draft_id: str, *, client_request_id: str | None = None,
              org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeQuote:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            draft_id = normalize_uuid(draft_id, "draft ID")
            body = _body(None, request_id, org_id, is_quote=True)
            return _quote(self._client._request("POST", f"{_PREFIX}/deployments/{draft_id}/quote", body=body,
                                               max_retries=0, timeout=timeout), "endpoint", draft_id, request_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    def launch(self, draft_id: str, *, quote_id: str, client_request_id: str | None = None,
               org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeEndpoint:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            draft_id = normalize_uuid(draft_id, "draft ID")
            body = _body(quote_id, request_id, org_id)
            return _endpoint(self._client._request("POST", f"{_PREFIX}/deployments/{draft_id}/launch", body=body,
                                                  max_retries=0, timeout=timeout), draft=draft_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    def list(self, *, org_id: str | None = None, limit: int | None = None, after_created_at: str | None = None,
             after_id: str | None = None, timeout: float | None = None) -> QueueRuntimeEndpointList:
        path = _PREFIX + "/endpoints" + _query(org_id, limit, after_created_at, after_id)
        return _page(QueueRuntimeEndpointList, self._client._request("GET", path, timeout=timeout), limit)

    def retrieve(self, endpoint_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeEndpoint:
        endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
        return _endpoint(self._client._request("GET", f"{_PREFIX}/endpoints/{endpoint_id}" + _query(org_id), timeout=timeout), endpoint_id)

    def stop(self, endpoint_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeStopResult:
        endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
        body = {} if org_id is None else {"org_id": normalize_uuid(org_id, "org_id")}
        return _parse(QueueRuntimeStopResult, self._client._request("POST", f"{_PREFIX}/endpoints/{endpoint_id}/stop",
                                                                 body=body, max_retries=0, timeout=timeout))


class AsyncQueueRuntimeEndpoints:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def quote(self, draft_id: str, *, client_request_id: str | None = None,
                    org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeQuote:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            draft_id = normalize_uuid(draft_id, "draft ID")
            body = _body(None, request_id, org_id, is_quote=True)
            return _quote(await self._client._request("POST", f"{_PREFIX}/deployments/{draft_id}/quote", body=body,
                                                     max_retries=0, timeout=timeout), "endpoint", draft_id, request_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    async def launch(self, draft_id: str, *, quote_id: str, client_request_id: str | None = None,
                     org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeEndpoint:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            draft_id = normalize_uuid(draft_id, "draft ID")
            body = _body(quote_id, request_id, org_id)
            return _endpoint(await self._client._request("POST", f"{_PREFIX}/deployments/{draft_id}/launch", body=body,
                                                        max_retries=0, timeout=timeout), draft=draft_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    async def list(self, *, org_id: str | None = None, limit: int | None = None, after_created_at: str | None = None,
                   after_id: str | None = None, timeout: float | None = None) -> QueueRuntimeEndpointList:
        path = _PREFIX + "/endpoints" + _query(org_id, limit, after_created_at, after_id)
        return _page(QueueRuntimeEndpointList, await self._client._request("GET", path, timeout=timeout), limit)

    async def retrieve(self, endpoint_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeEndpoint:
        endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
        return _endpoint(await self._client._request("GET", f"{_PREFIX}/endpoints/{endpoint_id}" + _query(org_id), timeout=timeout), endpoint_id)

    async def stop(self, endpoint_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeStopResult:
        endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
        body = {} if org_id is None else {"org_id": normalize_uuid(org_id, "org_id")}
        return _parse(QueueRuntimeStopResult, await self._client._request("POST", f"{_PREFIX}/endpoints/{endpoint_id}/stop",
                                                                       body=body, max_retries=0, timeout=timeout))


class QueueRuntimeJobs:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def quote(self, endpoint_id: str, *, input: dict[str, Any], client_request_id: str | None = None,
              org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeQuote:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
            body = _body(None, request_id, org_id, input, is_job=True, is_quote=True)
            return _quote(self._client._request("POST", f"{_PREFIX}/endpoints/{endpoint_id}/jobs/quote", body=body,
                                               max_retries=0, timeout=timeout), "job", endpoint_id, request_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    def create(self, endpoint_id: str, *, quote_id: str, input: dict[str, Any], client_request_id: str | None = None,
               org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeJob:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
            body = _body(quote_id, request_id, org_id, input, is_job=True)
            return _job(self._client._request("POST", f"{_PREFIX}/endpoints/{endpoint_id}/jobs", body=body,
                                             max_retries=0, timeout=timeout), endpoint_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    def list(self, endpoint_id: str, *, org_id: str | None = None, limit: int | None = None, after_created_at: str | None = None,
             after_id: str | None = None, timeout: float | None = None) -> QueueRuntimeJobList:
        endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
        path = f"{_PREFIX}/endpoints/{endpoint_id}/jobs" + _query(org_id, limit, after_created_at, after_id)
        return _page(QueueRuntimeJobList, self._client._request("GET", path, timeout=timeout), limit, endpoint_id)

    def retrieve(self, endpoint_id: str, job_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeJob:
        endpoint_id, job_id = normalize_uuid(endpoint_id, "endpoint ID"), normalize_uuid(job_id, "job ID")
        path = f"{_PREFIX}/endpoints/{endpoint_id}/jobs/{job_id}" + _query(org_id)
        return _job(self._client._request("GET", path, timeout=timeout), endpoint_id, job_id)

    def result(self, endpoint_id: str, job_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeResult:
        endpoint_id, job_id = normalize_uuid(endpoint_id, "endpoint ID"), normalize_uuid(job_id, "job ID")
        path = f"{_PREFIX}/endpoints/{endpoint_id}/jobs/{job_id}/result" + _query(org_id)
        return _parse(QueueRuntimeResult, self._client._request("GET", path, timeout=timeout))


class AsyncQueueRuntimeJobs:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def quote(self, endpoint_id: str, *, input: dict[str, Any], client_request_id: str | None = None,
                    org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeQuote:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
            body = _body(None, request_id, org_id, input, is_job=True, is_quote=True)
            return _quote(await self._client._request("POST", f"{_PREFIX}/endpoints/{endpoint_id}/jobs/quote", body=body,
                                                     max_retries=0, timeout=timeout), "job", endpoint_id, request_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    async def create(self, endpoint_id: str, *, quote_id: str, input: dict[str, Any], client_request_id: str | None = None,
                     org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeJob:
        request_id = normalize_uuid(client_request_id if client_request_id is not None else str(uuid4()), "client_request_id")
        try:
            endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
            body = _body(quote_id, request_id, org_id, input, is_job=True)
            return _job(await self._client._request("POST", f"{_PREFIX}/endpoints/{endpoint_id}/jobs", body=body,
                                                   max_retries=0, timeout=timeout), endpoint_id)
        except Exception as error:
            _identity(error, request_id)
            raise

    async def list(self, endpoint_id: str, *, org_id: str | None = None, limit: int | None = None, after_created_at: str | None = None,
                   after_id: str | None = None, timeout: float | None = None) -> QueueRuntimeJobList:
        endpoint_id = normalize_uuid(endpoint_id, "endpoint ID")
        path = f"{_PREFIX}/endpoints/{endpoint_id}/jobs" + _query(org_id, limit, after_created_at, after_id)
        return _page(QueueRuntimeJobList, await self._client._request("GET", path, timeout=timeout), limit, endpoint_id)

    async def retrieve(self, endpoint_id: str, job_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeJob:
        endpoint_id, job_id = normalize_uuid(endpoint_id, "endpoint ID"), normalize_uuid(job_id, "job ID")
        path = f"{_PREFIX}/endpoints/{endpoint_id}/jobs/{job_id}" + _query(org_id)
        return _job(await self._client._request("GET", path, timeout=timeout), endpoint_id, job_id)

    async def result(self, endpoint_id: str, job_id: str, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeResult:
        endpoint_id, job_id = normalize_uuid(endpoint_id, "endpoint ID"), normalize_uuid(job_id, "job ID")
        path = f"{_PREFIX}/endpoints/{endpoint_id}/jobs/{job_id}/result" + _query(org_id)
        return _parse(QueueRuntimeResult, await self._client._request("GET", path, timeout=timeout))


class ServerlessQueueRuntime:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client
        self.endpoints = QueueRuntimeEndpoints(client)
        self.jobs = QueueRuntimeJobs(client)

    def capabilities(self, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeCapabilities:
        return _parse(QueueRuntimeCapabilities, self._client._request("GET", _PREFIX + "/capabilities" + _query(org_id), timeout=timeout))


class AsyncServerlessQueueRuntime:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client
        self.endpoints = AsyncQueueRuntimeEndpoints(client)
        self.jobs = AsyncQueueRuntimeJobs(client)

    async def capabilities(self, *, org_id: str | None = None, timeout: float | None = None) -> QueueRuntimeCapabilities:
        return _parse(QueueRuntimeCapabilities, await self._client._request("GET", _PREFIX + "/capabilities" + _query(org_id), timeout=timeout))
