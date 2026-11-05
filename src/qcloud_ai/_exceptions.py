from __future__ import annotations

from typing import Any, Optional


class QCloudAIError(Exception):
    """Base exception for all QCloud AI SDK errors."""


class APIError(QCloudAIError):
    """Raised when the API returns a non-success status code."""

    request_id: Optional[str] = None
    status_code: int
    message: str
    error_type: Optional[str]
    body: Any

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        error_type: Optional[str] = None,
        body: Any = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.body = body
        super().__init__(f"[{status_code}] {message}")


class AuthenticationError(APIError):
    """Raised on 401 responses."""

    def __init__(self, message: str = "Invalid API key", **kwargs: Any) -> None:
        super().__init__(401, message, error_type="auth_error", **kwargs)


class PermissionDeniedError(APIError):
    """Raised on 403 responses."""

    def __init__(self, message: str = "Permission denied", **kwargs: Any) -> None:
        super().__init__(403, message, error_type="auth_error", **kwargs)


class NotFoundError(APIError):
    """Raised on 404 responses."""

    def __init__(self, message: str = "Resource not found", **kwargs: Any) -> None:
        super().__init__(404, message, error_type="invalid_request_error", **kwargs)


class RateLimitError(APIError):
    """Raised on 429 responses."""

    def __init__(self, message: str = "Rate limit exceeded", **kwargs: Any) -> None:
        super().__init__(429, message, error_type="rate_limit_error", **kwargs)


class InsufficientCreditsError(APIError):
    """Raised on 402 responses (billing)."""

    def __init__(self, message: str = "Insufficient credits", **kwargs: Any) -> None:
        super().__init__(402, message, error_type="billing_error", **kwargs)


class InternalServerError(APIError):
    """Raised on 5xx responses."""

    def __init__(
        self,
        status_code: int = 500,
        message: str = "Internal server error",
        **kwargs: Any,
    ) -> None:
        super().__init__(status_code, message, error_type="server_error", **kwargs)


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
    401: AuthenticationError,
    402: InsufficientCreditsError,
    403: PermissionDeniedError,
    404: NotFoundError,
    429: RateLimitError,
}


def _raise_for_status(status_code: int, body: Any) -> None:
    if 200 <= status_code < 300:
        return

    message = "Unknown error"
    error_type = None
    if isinstance(body, dict) and "error" in body:
        err = body["error"]
        if isinstance(err, dict):
            message = err.get("message", message)
            error_type = err.get("type")

    exc_cls = _STATUS_MAP.get(status_code)
    if exc_cls is not None:
        raise exc_cls(message, body=body)

    if status_code >= 500:
        raise InternalServerError(status_code, message, body=body)

    raise APIError(status_code, message, error_type=error_type, body=body)


class APIResponseValidationError(QCloudAIError):
    """The server returned invalid JSON or an unexpected streaming format."""
