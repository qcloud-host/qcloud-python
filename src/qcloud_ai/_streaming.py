from __future__ import annotations
import json
from typing import Any, Generic, Iterator, AsyncIterator, TypeVar
import httpx
from ._exceptions import (
    APIError,
    APIConnectionError,
    APITimeoutError,
    APIResponseValidationError,
)

T = TypeVar("T")


class _Decoder:
    def __init__(self) -> None:
        self.data: list[str] = []

    def feed(self, line: str) -> str | None:
        if line == "":
            if not self.data:
                return None
            payload = "\n".join(self.data)
            self.data = []
            return payload
        if line == "data" or line.startswith("data:"):
            value = line[5:]
            self.data.append(value[1:] if value.startswith(" ") else value)
        return None


def _parse(payload: str, cast: type[T]) -> T:
    try:
        data: Any = json.loads(payload)
    except ValueError as error:
        raise APIResponseValidationError("Invalid JSON in SSE data") from error
    if isinstance(data, dict) and "error" in data:
        error = data["error"]
        message = (
            error.get("message", "Streaming error")
            if isinstance(error, dict)
            else str(error)
        )
        raise APIError(200, message, body=data)
    return cast(**data) if isinstance(data, dict) else data


class Stream(Generic[T]):
    def __init__(self, response: httpx.Response, *, cast: type[T]) -> None:
        self._response = response
        self._cast = cast
        self._closed = False
        self._iterator = self._iter_events()

    def __iter__(self) -> Iterator[T]:
        return self

    def __next__(self) -> T:
        return next(self._iterator)

    def _iter_events(self) -> Iterator[T]:
        decoder = _Decoder()
        try:
            for line in self._response.iter_lines():
                if self._closed:
                    return
                payload = decoder.feed(line)
                if payload is None:
                    continue
                if payload.strip() == "[DONE]":
                    return
                yield _parse(payload, self._cast)
            payload = decoder.feed("")
            if payload is not None and payload.strip() != "[DONE]":
                yield _parse(payload, self._cast)
        except httpx.TimeoutException as error:
            raise APITimeoutError() from error
        except httpx.TransportError as error:
            raise APIConnectionError(cause=error) from error
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._response.close()

    def __enter__(self) -> Stream[T]:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AsyncStream(Generic[T]):
    def __init__(self, response: httpx.Response, *, cast: type[T]) -> None:
        self._response = response
        self._cast = cast
        self._closed = False
        self._iterator = self._iter_events()

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        return await self._iterator.__anext__()

    async def _iter_events(self) -> AsyncIterator[T]:
        decoder = _Decoder()
        try:
            async for line in self._response.aiter_lines():
                if self._closed:
                    return
                payload = decoder.feed(line)
                if payload is None:
                    continue
                if payload.strip() == "[DONE]":
                    return
                yield _parse(payload, self._cast)
            payload = decoder.feed("")
            if payload is not None and payload.strip() != "[DONE]":
                yield _parse(payload, self._cast)
        except httpx.TimeoutException as error:
            raise APITimeoutError() from error
        except httpx.TransportError as error:
            raise APIConnectionError(cause=error) from error
        finally:
            await self.close()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._response.aclose()

    async def __aenter__(self) -> AsyncStream[T]:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
