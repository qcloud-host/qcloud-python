from __future__ import annotations

import math
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Optional


class QCloudAIError(Exception):
    """Base exception for all QCloud AI SDK errors."""

    client_request_id: str | None = None


def _integer_header(headers: Mapping[str, str], name: str) -> Optional[int]:
    value = headers.get(name)
    if value is None:
        return None
    try:
        number = int(value.strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    """Parse ``Retry-After`` as delta-seconds or an HTTP date, if valid."""
    if value is None:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError, IndexError):
            return None
    if not math.isfinite(delay):
        return None
    return max(0.0, delay)


@dataclass(frozen=True)
class RateLimitInfo:
    """Limits reported by the QCloud admission layer for the failed request.

    Values are ``None`` when the API did not report them. They describe
    QCloud's request admission, not a provider's final billing limit.
    """

    limit_requests: Optional[int] = None
    remaining_requests: Optional[int] = None
    limit_tokens: Optional[int] = None
    remaining_tokens: Optional[int] = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> Optional["RateLimitInfo"]:
        info = cls(
            limit_requests=_integer_header(headers, "x-ratelimit-limit-requests"),
            remaining_requests=_integer_header(
                headers, "x-ratelimit-remaining-requests"
            ),
            limit_tokens=_integer_header(headers, "x-ratelimit-limit-tokens"),
            remaining_tokens=_integer_header(headers, "x-ratelimit-remaining-tokens"),
        )
        return None if info == cls() else info


class APIError(QCloudAIError):
    """Raised when the API returns a non-success status code.

    ``request_id`` identifies the request in QCloud logs and support requests.
    ``headers`` are the response headers, ``retry_after`` is the parsed
    ``Retry-After`` delay in seconds and ``rate_limit`` carries any reported
    admission limits. ``code`` is the machine-readable error code when the API
    returns one.
    """

    request_id: Optional[str] = None
    headers: Optional[Mapping[str, str]] = None
    retry_after: Optional[float] = None
    rate_limit: Optional[RateLimitInfo] = None
    status_code: int
    message: str
    error_type: Optional[str]
    code: Optional[str]
    body: Any

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        error_type: Optional[str] = None,
        code: Optional[str] = None,
        body: Any = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.code = code
        self.body = body
        super().__init__(f"[{status_code}] {message}")

    def _attach_headers(self, headers: Optional[Mapping[str, str]]) -> None:
        if headers is None:
            return
        self.headers = headers
        self.request_id = headers.get("x-request-id") or headers.get("request-id")
        self.retry_after = _retry_after_seconds(headers.get("retry-after"))
        self.rate_limit = RateLimitInfo.from_headers(headers)


class BadRequestError(APIError):
    """Raised on 400 responses, including features rejected before dispatch."""

    def __init__(self, message: str = "Bad request", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "invalid_request_error")
        super().__init__(400, message, **kwargs)


class AuthenticationError(APIError):
    """Raised on 401 responses."""

    def __init__(self, message: str = "Invalid API key", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "auth_error")
        super().__init__(401, message, **kwargs)


class PermissionDeniedError(APIError):
    """Raised on 403 responses."""

    def __init__(self, message: str = "Permission denied", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "auth_error")
        super().__init__(403, message, **kwargs)


class NotFoundError(APIError):
    """Raised on 404 responses."""

    def __init__(self, message: str = "Resource not found", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "invalid_request_error")
        super().__init__(404, message, **kwargs)


class ConflictError(APIError):
    """Raised on 409 responses, such as a reused idempotency identity."""

    def __init__(self, message: str = "Conflict", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "conflict_error")
        super().__init__(409, message, **kwargs)


class UnprocessableEntityError(APIError):
    """Raised on 422 responses."""

    def __init__(self, message: str = "Unprocessable request", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "invalid_request_error")
        super().__init__(422, message, **kwargs)


class RateLimitError(APIError):
    """Raised on 429 responses. See ``retry_after`` and ``rate_limit``."""

    def __init__(self, message: str = "Rate limit exceeded", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "rate_limit_error")
        super().__init__(429, message, **kwargs)


class InsufficientCreditsError(APIError):
    """Raised on 402 responses (billing)."""

    def __init__(self, message: str = "Insufficient credits", **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "billing_error")
        super().__init__(402, message, **kwargs)


class InternalServerError(APIError):
    """Raised on 5xx responses."""

    def __init__(
        self,
        status_code: int = 500,
        message: str = "Internal server error",
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("error_type", "server_error")
        super().__init__(status_code, message, **kwargs)


class APIConnectionError(QCloudAIError):
    """Raised when the SDK cannot reach the API."""

    def __init__(
        self, message: str = "Connection error", *, cause: Optional[Exception] = None
    ) -> None:
        self.cause = cause
        super().__init__(message)


class APITimeoutError(APIConnectionError):
    """Raised when a request times out."""

    def __init__(self, message: str = "Request timed out") -> None:
        super().__init__(message)


_STATUS_MAP: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: InsufficientCreditsError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def _raise_for_status(
    status_code: int, body: Any, headers: Optional[Mapping[str, str]] = None
) -> None:
    if 200 <= status_code < 300:
        return

    message = "Unknown error"
    error_type = None
    code = None
    if isinstance(body, dict) and "error" in body:
        err = body["error"]
        if isinstance(err, dict):
            if isinstance(err.get("message"), str):
                message = err["message"]
            if isinstance(err.get("type"), str):
                error_type = err["type"]
            if isinstance(err.get("code"), str):
                code = err["code"]
        elif isinstance(err, str):
            message = err

    details: dict[str, Any] = {"body": body, "code": code}
    if error_type is not None:
        details["error_type"] = error_type
    exc_cls = _STATUS_MAP.get(status_code)
    if exc_cls is not None:
        error: APIError = exc_cls(message, **details)
    elif status_code >= 500:
        error = InternalServerError(status_code, message, **details)
    else:
        error = APIError(status_code, message, **details)
    error._attach_headers(headers)
    raise error


class APIResponseValidationError(QCloudAIError):
    """The server returned invalid JSON, a mismatched schema, or an invalid stream.

    ``status_code`` and ``request_id`` are included when the response is available.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(message)
