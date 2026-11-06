from __future__ import annotations
import asyncio
import math
import os
import random
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, TypeVar
from urllib.parse import urlsplit
import httpx
from ._exceptions import (
    APIError,
    APIConnectionError,
    APITimeoutError,
    APIResponseValidationError,
    _raise_for_status,
)

DEFAULT_BASE_URL = "https://www.qcloud.host/api/v1"
DEFAULT_TIMEOUT = 600.0
DEFAULT_MAX_RETRIES = 2
SDK_VERSION = "0.2.0"


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    value = response.headers.get("retry-after") if response else None
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                delay = -1
        if 0 <= delay <= 60:
            return delay
    return min(0.5 * 2**attempt, 8) * (0.75 + random.random() * 0.25)


def _validate_response(response: httpx.Response, stream: bool) -> None:
    if not 200 <= response.status_code < 300:
        try:
            data = response.json()
        except ValueError:
            data = {"error": {"message": response.text[:500] or response.reason_phrase}}
        try:
            _raise_for_status(response.status_code, data)
        except APIError as error:
            error.request_id = response.headers.get("x-request-id")
            raise
    if stream:
        if "text/event-stream" not in response.headers.get("content-type", ""):
            raise APIResponseValidationError(
                "Expected an SSE response from the streaming endpoint"
            )
    else:
        try:
            response.json()
        except ValueError as error:
            raise APIResponseValidationError("The API returned invalid JSON") from error


class BaseClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.environ.get("QCLOUD_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError(
                "No API key provided. Pass api_key= or set QCLOUD_API_KEY."
            )
        self.base_url = (
            base_url
            if base_url is not None
            else os.environ.get("QCLOUD_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        url = urlsplit(self.base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.netloc
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "base_url must be an HTTP(S) URL without credentials, query, or fragment"
            )
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.max_retries = (
            max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
        )
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        self._custom_headers = dict(default_headers or {})
        self.organization = (
            organization
            if organization is not None
            else os.environ.get("QCLOUD_ORGANIZATION_ID")
        )
        if self.organization and not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", self.organization
        ):
            raise ValueError("organization must be an organization UUID")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"qcloud-ai-python/{SDK_VERSION}",
            **(
                {"X-QCloud-Organization": self.organization}
                if self.organization
                else {}
            ),
            **self._custom_headers,
        }

    def _make_url(self, path: str) -> str:
        return f"{self.base_url}{path}"


SyncClientT = TypeVar("SyncClientT", bound="SyncHTTPClient")
AsyncClientT = TypeVar("AsyncClientT", bound="AsyncHTTPClient")


class SyncHTTPClient(BaseClient):
    def __init__(
        self, *, http_client: httpx.Client | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._client = http_client or httpx.Client(
            timeout=self.timeout, follow_redirects=False
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                request = self._client.build_request(
                    method,
                    self._make_url(path),
                    headers=self._headers,
                    json=body,
                    timeout=self.timeout,
                )
                response = self._client.send(
                    request, stream=stream, follow_redirects=False
                )
                if attempt < self.max_retries and (
                    response.status_code == 429
                    or (
                        method == "GET"
                        and (
                            response.status_code in (408, 409)
                            or response.status_code >= 500
                        )
                    )
                ):
                    delay = _retry_delay(response, attempt)
                    response.close()
                    time.sleep(delay)
                    continue
                if not 200 <= response.status_code < 300:
                    response.read()
                _validate_response(response, stream)
                return response
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if response is not None:
                    response.close()
                # An ambiguous POST failure may already have generated billable output.
                if method == "GET" and attempt < self.max_retries:
                    time.sleep(_retry_delay(None, attempt))
                    continue
                if isinstance(error, httpx.TimeoutException):
                    raise APITimeoutError() from error
                raise APIConnectionError(cause=error) from error
            except BaseException:
                if response is not None:
                    response.close()
                raise
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._client.close()

    def __enter__(self: SyncClientT) -> SyncClientT:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AsyncHTTPClient(BaseClient):
    def __init__(
        self, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._client = http_client or httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=False
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                request = self._client.build_request(
                    method,
                    self._make_url(path),
                    headers=self._headers,
                    json=body,
                    timeout=self.timeout,
                )
                response = await self._client.send(
                    request, stream=stream, follow_redirects=False
                )
                if attempt < self.max_retries and (
                    response.status_code == 429
                    or (
                        method == "GET"
                        and (
                            response.status_code in (408, 409)
                            or response.status_code >= 500
                        )
                    )
                ):
                    delay = _retry_delay(response, attempt)
                    await response.aclose()
                    await asyncio.sleep(delay)
                    continue
                if not 200 <= response.status_code < 300:
                    await response.aread()
                _validate_response(response, stream)
                return response
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if response is not None:
                    await response.aclose()
                if method == "GET" and attempt < self.max_retries:
                    await asyncio.sleep(_retry_delay(None, attempt))
                    continue
                if isinstance(error, httpx.TimeoutException):
                    raise APITimeoutError() from error
                raise APIConnectionError(cause=error) from error
            except BaseException:
                if response is not None:
                    await response.aclose()
                raise
        raise AssertionError("unreachable")

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self: AsyncClientT) -> AsyncClientT:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
