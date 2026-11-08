from __future__ import annotations

import re
from typing import Any, AsyncIterator, Iterator

import httpx

from ._exceptions import APIConnectionError, APIResponseValidationError, APITimeoutError

MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024


class _FileMetadata:
    def __init__(self, response: httpx.Response, job_id: str, asset_id: str, max_bytes: int) -> None:
        if response.status_code not in (200, 206):
            raise APIResponseValidationError("Expected a binary download response")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise APIResponseValidationError("Unexpected download content encoding")
        length = response.headers.get("content-length")
        if length is not None and (not re.fullmatch(r"[0-9]{1,16}", length) or int(length) > 2**53 - 1):
            raise APIResponseValidationError("Invalid download content length")
        self.content_length = int(length) if length is not None else None
        if self.content_length is not None and self.content_length > max_bytes:
            raise APIResponseValidationError("Download exceeds max_bytes")
        self.job_id, self.asset_id = job_id, asset_id
        self.status_code = response.status_code
        self.content_type = response.headers.get("content-type", "application/octet-stream")
        self.content_range = response.headers.get("content-range")
        self.accept_ranges = response.headers.get("accept-ranges")
        self.request_id = response.headers.get("x-request-id")
        self._response, self._max_bytes = response, max_bytes
        self._consumed = self._closed = False
        self.bytes_read = 0

    def _accept(self, chunk: bytes) -> bytes:
        self.bytes_read += len(chunk)
        if self.bytes_read > self._max_bytes:
            raise APIResponseValidationError("Download exceeds max_bytes")
        if self.content_length is not None and self.bytes_read > self.content_length:
            raise APIResponseValidationError("Download exceeds its declared content length")
        return chunk

    def _finish(self) -> None:
        if self.content_length is not None and self.bytes_read != self.content_length:
            raise APIResponseValidationError("Download ended before the declared content length")


class GenerationFile(_FileMetadata):
    """Single-use binary download. Use as a context manager, including on early exit."""

    def iter_bytes(self) -> Iterator[bytes]:
        if self._consumed:
            raise RuntimeError("This download has already been consumed")
        self._consumed = True
        try:
            if self._closed:
                return
            for chunk in self._response.iter_raw(chunk_size=65536):
                if self._closed:
                    return
                yield self._accept(chunk)
            self._finish()
        except httpx.TimeoutException as error:
            raise APITimeoutError() from error
        except httpx.TransportError as error:
            raise APIConnectionError("Download connection was interrupted", cause=error) from error
        finally:
            self.close()

    def __iter__(self) -> Iterator[bytes]:
        return self.iter_bytes()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._response.close()

    def __enter__(self) -> GenerationFile:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AsyncGenerationFile(_FileMetadata):
    """Single-use async binary download; cancellation closes the HTTP response."""

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        if self._consumed:
            raise RuntimeError("This download has already been consumed")
        self._consumed = True
        try:
            if self._closed:
                return
            async for chunk in self._response.aiter_raw(chunk_size=65536):
                if self._closed:
                    return
                yield self._accept(chunk)
            self._finish()
        except httpx.TimeoutException as error:
            raise APITimeoutError() from error
        except httpx.TransportError as error:
            raise APIConnectionError("Download connection was interrupted", cause=error) from error
        finally:
            await self.close()

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self.iter_bytes()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._response.aclose()

    async def __aenter__(self) -> AsyncGenerationFile:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
