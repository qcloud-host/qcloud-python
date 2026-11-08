from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable
from typing import Any, Literal, TypeVar
from urllib.parse import quote, urlencode
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from .._base_client import AsyncHTTPClient, SyncHTTPClient
from .._exceptions import APIResponseValidationError, APITimeoutError, QCloudAIError
from .._uuid import normalize_uuid
from ..types.generation import (
    GenerationJob,
    GenerationModel,
    GenerationModelList,
    GenerationPendingResult,
    GenerationResult,
    GenerationSubscription,
)
from .generation_sessions import AsyncGenerationSessions, GenerationSessions


class GenerationJobError(QCloudAIError):
    def __init__(self, job: GenerationJob) -> None:
        self.job = job
        super().__init__(
            (job.error or {}).get("message", f"Generation job {job.status}")
        )


class GenerationTimeoutError(APITimeoutError):
    def __init__(
        self, job_id: str | None = None, client_request_id: str | None = None
    ) -> None:
        self.job_id = job_id
        self.client_request_id = client_request_id
        super().__init__("Generation polling timed out; the job may still be running")


ModelT = TypeVar("ModelT", bound=BaseModel)


def _parse(model: type[ModelT], value: Any) -> ModelT:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise APIResponseValidationError(
            "The API returned an invalid generation response"
        ) from error


def _path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("An ID is required")
    return quote(value, safe="")


def _submission(
    model: str,
    input: Any,
    billing_mode: str,
    client_request_id: str | None,
    timeout_seconds: int | None,
) -> dict[str, Any]:
    _path(model)
    if billing_mode != "metered":
        raise ValueError(
            "billing_mode='metered' is required to accept variable usage charges"
        )
    # Preserve primitives, arrays, and nested objects; reject non-JSON/NaN inputs.
    json.dumps(input, allow_nan=False)
    request_id = normalize_uuid(
        client_request_id if client_request_id is not None else str(uuid4()),
        "client_request_id",
    )
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 86400
    ):
        raise ValueError("timeout_seconds must be an integer from 1 to 86400")
    return {
        "model": model,
        "input": input,
        "billing_mode": "metered",
        "client_request_id": request_id,
        **({"timeout_seconds": timeout_seconds} if timeout_seconds is not None else {}),
    }


def _result(id: str, value: Any) -> GenerationResult[Any] | GenerationPendingResult:
    if not isinstance(value, dict):
        raise APIResponseValidationError(
            "The API returned an invalid generation result"
        )
    if "job_id" in value:
        result = _parse(GenerationResult[Any], value)
        if result.job_id != id:
            raise APIResponseValidationError(
                "The generation result belongs to a different job"
            )
        return result
    pending = _parse(GenerationPendingResult, value)
    if pending.data.id != id:
        raise APIResponseValidationError("The API returned a different generation job")
    return pending


class _Deadline:
    def __init__(
        self,
        timeout: float,
        poll_interval: float,
        job_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        if not math.isfinite(poll_interval) or not 0 < poll_interval <= 60:
            raise ValueError(
                "poll_interval must be positive and no greater than 60 seconds"
            )
        self.end = time.monotonic() + timeout
        self.interval = poll_interval
        self.job_id = job_id
        self.request_id = request_id

    def remaining(self) -> float:
        value = self.end - time.monotonic()
        if value <= 0:
            raise GenerationTimeoutError(self.job_id, self.request_id)
        return value


def _checked_job(value: Any, expected_id: str | None = None) -> GenerationJob:
    result = _parse(GenerationJob, value)
    if expected_id is not None and result.id != expected_id:
        raise APIResponseValidationError("The API returned a different generation job")
    return result


def _data(value: Any) -> Any:
    return value.get("data") if isinstance(value, dict) else None


class GenerationModels:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def list(
        self,
        *,
        q: str | None = None,
        category: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> GenerationModelList:
        query = urlencode(
            {
                key: value
                for key, value in {
                    "q": q,
                    "category": category,
                    "status": status,
                    "limit": limit,
                    "cursor": cursor,
                }.items()
                if value is not None
            }
        )
        response = self._client._request(
            "GET", f"/generation/models{'?' + query if query else ''}"
        )
        return _parse(GenerationModelList, response.json())

    def retrieve(self, id: str) -> GenerationModel:
        return _parse(
            GenerationModel,
            self._client._request("GET", f"/generation/models/{_path(id)}").json(),
        )

    def schema(self, id: str) -> dict[str, Any]:
        value = self._client._request(
            "GET", f"/generation/models/{_path(id)}/schema"
        ).json()
        if not isinstance(value, dict):
            raise APIResponseValidationError("The API returned an invalid model schema")
        return value


class AsyncGenerationModels:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def list(
        self,
        *,
        q: str | None = None,
        category: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> GenerationModelList:
        query = urlencode(
            {
                key: value
                for key, value in {
                    "q": q,
                    "category": category,
                    "status": status,
                    "limit": limit,
                    "cursor": cursor,
                }.items()
                if value is not None
            }
        )
        response = await self._client._request(
            "GET", f"/generation/models{'?' + query if query else ''}"
        )
        return _parse(GenerationModelList, response.json())

    async def retrieve(self, id: str) -> GenerationModel:
        return _parse(
            GenerationModel,
            (
                await self._client._request("GET", f"/generation/models/{_path(id)}")
            ).json(),
        )

    async def schema(self, id: str) -> dict[str, Any]:
        value = (
            await self._client._request("GET", f"/generation/models/{_path(id)}/schema")
        ).json()
        if not isinstance(value, dict):
            raise APIResponseValidationError("The API returned an invalid model schema")
        return value


class GenerationJobs:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def submit(
        self,
        *,
        model: str,
        input: Any,
        billing_mode: Literal["metered"],
        client_request_id: str | None = None,
        timeout_seconds: int | None = None,
        timeout: float | None = None,
    ) -> GenerationJob:
        body = _submission(
            model, input, billing_mode, client_request_id, timeout_seconds
        )
        try:
            response = self._client._request(
                "POST", "/generation/jobs", body=body, timeout=timeout, max_retries=0
            )
            return _checked_job(_data(response.json()))
        except QCloudAIError as error:
            error.client_request_id = body["client_request_id"]
            raise

    def retrieve(self, id: str, *, timeout: float | None = None) -> GenerationJob:
        id = normalize_uuid(id, "job ID")
        response = self._client._request(
            "GET", f"/generation/jobs/{_path(id)}", timeout=timeout, max_retries=0
        )
        return _checked_job(_data(response.json()), id)

    def cancel(self, id: str, *, timeout: float | None = None) -> GenerationJob:
        id = normalize_uuid(id, "job ID")
        response = self._client._request(
            "POST",
            f"/generation/jobs/{_path(id)}/cancel",
            timeout=timeout,
            max_retries=0,
        )
        return _checked_job(_data(response.json()), id)

    def result(
        self, id: str, *, timeout: float | None = None
    ) -> GenerationResult[Any] | GenerationPendingResult:
        id = normalize_uuid(id, "job ID")
        return _result(
            id,
            self._client._request(
                "GET",
                f"/generation/jobs/{_path(id)}/result",
                timeout=timeout,
                max_retries=0,
            ).json(),
        )

    def _poll(
        self,
        id: str,
        deadline: _Deadline,
        on_update: Callable[[GenerationJob], None] | None,
    ) -> GenerationJob:
        while True:
            try:
                current = self.retrieve(
                    id, timeout=min(self._client.timeout, deadline.remaining())
                )
            except APITimeoutError:
                deadline.remaining()
                raise
            deadline.remaining()
            if on_update is not None:
                on_update(current)
            if current.status in ("failed", "cancelled", "review"):
                raise GenerationJobError(current)
            if current.status == "succeeded":
                return current
            time.sleep(min(deadline.interval, deadline.remaining()))

    def wait(
        self,
        id: str,
        *,
        timeout: float = 600,
        poll_interval: float = 1,
        on_update: Callable[[GenerationJob], None] | None = None,
    ) -> GenerationJob:
        id = normalize_uuid(id, "job ID")
        return self._poll(id, _Deadline(timeout, poll_interval, id), on_update)

    def subscribe(
        self,
        *,
        model: str,
        input: Any,
        billing_mode: Literal["metered"],
        client_request_id: str | None = None,
        timeout_seconds: int | None = None,
        timeout: float = 600,
        poll_interval: float = 1,
        on_update: Callable[[GenerationJob], None] | None = None,
    ) -> GenerationSubscription[Any]:
        request_id = normalize_uuid(
            client_request_id if client_request_id is not None else str(uuid4()),
            "client_request_id",
        )
        deadline = _Deadline(timeout, poll_interval, request_id=request_id)
        try:
            submitted = self.submit(
                model=model,
                input=input,
                billing_mode=billing_mode,
                client_request_id=request_id,
                timeout_seconds=timeout_seconds,
                timeout=min(self._client.timeout, deadline.remaining()),
            )
            deadline.job_id = submitted.id
            while True:
                completed = self._poll(submitted.id, deadline, on_update)
                result = self.result(
                    submitted.id,
                    timeout=min(self._client.timeout, deadline.remaining()),
                )
                deadline.remaining()
                if isinstance(result, GenerationResult):
                    return GenerationSubscription(job=completed, result=result)
                time.sleep(min(deadline.interval, deadline.remaining()))
        except APITimeoutError:
            deadline.remaining()
            raise


class AsyncGenerationJobs:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def submit(
        self,
        *,
        model: str,
        input: Any,
        billing_mode: Literal["metered"],
        client_request_id: str | None = None,
        timeout_seconds: int | None = None,
        timeout: float | None = None,
    ) -> GenerationJob:
        body = _submission(
            model, input, billing_mode, client_request_id, timeout_seconds
        )
        try:
            response = await self._client._request(
                "POST", "/generation/jobs", body=body, timeout=timeout, max_retries=0
            )
            return _checked_job(_data(response.json()))
        except QCloudAIError as error:
            error.client_request_id = body["client_request_id"]
            raise

    async def retrieve(self, id: str, *, timeout: float | None = None) -> GenerationJob:
        id = normalize_uuid(id, "job ID")
        response = await self._client._request(
            "GET", f"/generation/jobs/{_path(id)}", timeout=timeout, max_retries=0
        )
        return _checked_job(_data(response.json()), id)

    async def cancel(self, id: str, *, timeout: float | None = None) -> GenerationJob:
        id = normalize_uuid(id, "job ID")
        response = await self._client._request(
            "POST",
            f"/generation/jobs/{_path(id)}/cancel",
            timeout=timeout,
            max_retries=0,
        )
        return _checked_job(_data(response.json()), id)

    async def result(
        self, id: str, *, timeout: float | None = None
    ) -> GenerationResult[Any] | GenerationPendingResult:
        id = normalize_uuid(id, "job ID")
        return _result(
            id,
            (
                await self._client._request(
                    "GET",
                    f"/generation/jobs/{_path(id)}/result",
                    timeout=timeout,
                    max_retries=0,
                )
            ).json(),
        )

    async def _bounded(self, awaitable: Any, deadline: _Deadline) -> Any:
        try:
            remaining = deadline.remaining()
        except BaseException:
            awaitable.close()
            raise
        try:
            return await asyncio.wait_for(awaitable, remaining)
        except (asyncio.TimeoutError, APITimeoutError) as error:
            if time.monotonic() >= deadline.end or isinstance(
                error, asyncio.TimeoutError
            ):
                raise GenerationTimeoutError(
                    deadline.job_id, deadline.request_id
                ) from error
            raise

    async def _poll(
        self,
        id: str,
        deadline: _Deadline,
        on_update: Callable[[GenerationJob], None] | None,
    ) -> GenerationJob:
        while True:
            current = await self._bounded(
                self.retrieve(
                    id, timeout=min(self._client.timeout, deadline.remaining())
                ),
                deadline,
            )
            if on_update is not None:
                on_update(current)
            if current.status in ("failed", "cancelled", "review"):
                raise GenerationJobError(current)
            if current.status == "succeeded":
                return current
            await asyncio.sleep(min(deadline.interval, deadline.remaining()))

    async def wait(
        self,
        id: str,
        *,
        timeout: float = 600,
        poll_interval: float = 1,
        on_update: Callable[[GenerationJob], None] | None = None,
    ) -> GenerationJob:
        id = normalize_uuid(id, "job ID")
        return await self._poll(id, _Deadline(timeout, poll_interval, id), on_update)

    async def subscribe(
        self,
        *,
        model: str,
        input: Any,
        billing_mode: Literal["metered"],
        client_request_id: str | None = None,
        timeout_seconds: int | None = None,
        timeout: float = 600,
        poll_interval: float = 1,
        on_update: Callable[[GenerationJob], None] | None = None,
    ) -> GenerationSubscription[Any]:
        request_id = normalize_uuid(
            client_request_id if client_request_id is not None else str(uuid4()),
            "client_request_id",
        )
        deadline = _Deadline(timeout, poll_interval, request_id=request_id)
        submitted = await self._bounded(
            self.submit(
                model=model,
                input=input,
                billing_mode=billing_mode,
                client_request_id=request_id,
                timeout_seconds=timeout_seconds,
                timeout=min(self._client.timeout, deadline.remaining()),
            ),
            deadline,
        )
        deadline.job_id = submitted.id
        while True:
            completed = await self._poll(submitted.id, deadline, on_update)
            result = await self._bounded(
                self.result(
                    submitted.id,
                    timeout=min(self._client.timeout, deadline.remaining()),
                ),
                deadline,
            )
            if isinstance(result, GenerationResult):
                return GenerationSubscription(job=completed, result=result)
            await asyncio.sleep(min(deadline.interval, deadline.remaining()))


class Generation:
    def __init__(self, client: SyncHTTPClient) -> None:
        self.models = GenerationModels(client)
        self.jobs = GenerationJobs(client)
        self.sessions = GenerationSessions(client)


class AsyncGeneration:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self.models = AsyncGenerationModels(client)
        self.jobs = AsyncGenerationJobs(client)
        self.sessions = AsyncGenerationSessions(client)
