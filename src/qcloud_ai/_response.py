"""Consistent errors for JSON responses that do not match a resource schema."""

from __future__ import annotations

from typing import TypeVar

import httpx
from pydantic import BaseModel

from ._exceptions import APIResponseValidationError

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def parse_response(response: httpx.Response, schema: type[ResponseT]) -> ResponseT:
    try:
        return schema.model_validate(response.json())
    except (ValueError, TypeError):
        # Do not include response values: they can contain private prompts/output.
        raise APIResponseValidationError(
            f"The API returned an invalid {schema.__name__} response",
            status_code=response.status_code,
            request_id=response.headers.get("x-request-id")
            or response.headers.get("request-id"),
        ) from None
