from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any, Literal, TypeVar
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ValidationError

from .._base_client import AsyncHTTPClient, SyncHTTPClient
from .._exceptions import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    QCloudAIError,
)
from ..types.generation import (
    GenerationSession,
    GenerationSessionConnection,
    GenerationSessionEvent,
    GenerationWebRTCConnection,
    GenerationWebRTCSignalingConnection,
    GenerationWebSocketConnection,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _id(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value.lower():
        raise ValueError("A session UUID is required")
    return value


def _parse(model: type[ModelT], value: Any) -> ModelT:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise APIResponseValidationError(
            "Invalid generation session response"
        ) from error


def _data(value: Any) -> Any:
    if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
        raise APIResponseValidationError("Invalid session response envelope")
    return value["data"]


def _session(value: Any, id: str | None = None) -> GenerationSession:
    result = _parse(GenerationSession, _data(value))
    if id is not None and result.id != id:
        raise APIResponseValidationError("Response belongs to a different session")
    return result


def _connection(value: Any, id: str) -> GenerationSessionConnection:
    data = _data(value)
    result: GenerationSessionConnection
    if data.get("transport") == "websocket":
        result = _parse(GenerationWebSocketConnection, data)
    elif data.get("signaling") == "websocket":
        result = _parse(GenerationWebRTCSignalingConnection, data)
    else:
        result = _parse(GenerationWebRTCConnection, data)
    if result.session_id is not None and result.session_id != id:
        raise APIResponseValidationError("Connection belongs to a different session")
    if not result.token:
        raise APIResponseValidationError("Session capability has no token")
    if isinstance(
        result, (GenerationWebSocketConnection, GenerationWebRTCSignalingConnection)
    ):
        if (
            not result.websocket_url
            or not result.subprotocols
            or any(not item for item in result.subprotocols)
        ):
            raise APIResponseValidationError("Invalid signaling socket capability")
    elif not result.url:
        raise APIResponseValidationError("Invalid WebRTC session capability")
    return result


def _create(
    model: str,
    transport: str,
    billing_mode: str,
    client_request_id: str | None,
    max_duration_seconds: int | None,
) -> dict[str, Any]:
    if not model or transport not in ("websocket", "webrtc"):
        raise ValueError("A model and supported session transport are required")
    if billing_mode != "metered":
        raise ValueError("billing_mode='metered' is required")
    request_id = _id(
        client_request_id if client_request_id is not None else str(uuid4())
    )
    if max_duration_seconds is not None and (
        isinstance(max_duration_seconds, bool)
        or not isinstance(max_duration_seconds, int)
        or not 1 <= max_duration_seconds <= 3600
    ):
        raise ValueError("max_duration_seconds must be an integer from 1 to 3600")
    return {
        "model": model,
        "transport": transport,
        "billing_mode": billing_mode,
        "client_request_id": request_id,
        **(
            {}
            if max_duration_seconds is None
            else {"max_duration_seconds": max_duration_seconds}
        ),
    }


def _offer(sdp: str, type: str, token: str) -> dict[str, str]:
    if (
        type != "offer"
        or not isinstance(sdp, str)
        or not sdp
        or not token
        or "\r" in token
        or "\n" in token
    ):
        raise ValueError("An SDP offer and session token are required")
    return {"type": "offer", "sdp": sdp}


class _SessionDecoder:
    def __init__(self, id: str) -> None:
        self.id, self.event, self.data, self.size, self.answered = id, "", [], 0, False

    def feed(self, line: str) -> GenerationSessionEvent | None:
        if line == "":
            if not self.data:
                self.event = ""
                return None
            try:
                value = json.loads("\n".join(self.data))
            except ValueError as error:
                raise APIResponseValidationError(
                    "Invalid JSON in session event"
                ) from error
            event = self.event
            self.event, self.data, self.size = "", [], 0
            if not isinstance(value, dict):
                raise APIResponseValidationError("Invalid session event")
            if event == "error":
                error = (
                    value.get("error") if isinstance(value.get("error"), dict) else {}
                )
                raise APIError(
                    200,
                    error.get("message", "Session connection failed"),
                    error_type=error.get("code"),
                    body=value,
                )
            if value.get("session_id") != self.id:
                raise APIResponseValidationError("Event belongs to a different session")
            if event == "answer":
                if (
                    self.answered
                    or value.get("type") != "answer"
                    or not isinstance(value.get("sdp"), str)
                    or not value["sdp"]
                ):
                    raise APIResponseValidationError(
                        "Invalid or duplicate session answer"
                    )
                self.answered = True
            elif event != "closed" or not isinstance(value.get("reason"), str):
                raise APIResponseValidationError("Unknown session event")
            return GenerationSessionEvent(event=event, data=value)
        if line == "data" or line.startswith("data:"):
            part = line[5:]
            self.data.append(part[1:] if part.startswith(" ") else part)
            self.size += len(part)
        elif line.startswith("event:"):
            self.event = line[6:].removeprefix(" ")
        if self.size > 2_097_152 or len(line) > 2_097_152:
            raise APIResponseValidationError("Session event exceeds the size limit")
        return None


class GenerationSessionStream:
    def __init__(self, response: httpx.Response, id: str) -> None:
        self._response, self.session_id, self._closed = response, id, False
        self._iterator = self._events()

    def __iter__(self) -> Iterator[GenerationSessionEvent]:
        return self

    def __next__(self) -> GenerationSessionEvent:
        return next(self._iterator)

    def _events(self) -> Iterator[GenerationSessionEvent]:
        decoder = _SessionDecoder(self.session_id)
        try:
            for line in self._response.iter_lines():
                if self._closed:
                    return
                event = decoder.feed(line)
                if event is not None:
                    yield event
                    if event.event == "closed":
                        return
            if not self._closed:
                raise APIResponseValidationError(
                    "Session stream ended unexpectedly; retrieve session status and billing"
                )
        except APIError as error:
            error.request_id = self._response.headers.get("x-request-id")
            raise
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

    def __enter__(self) -> GenerationSessionStream:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AsyncGenerationSessionStream:
    def __init__(self, response: httpx.Response, id: str) -> None:
        self._response, self.session_id, self._closed = response, id, False
        self._iterator = self._events()

    def __aiter__(self) -> AsyncIterator[GenerationSessionEvent]:
        return self

    async def __anext__(self) -> GenerationSessionEvent:
        return await self._iterator.__anext__()

    async def _events(self) -> AsyncIterator[GenerationSessionEvent]:
        decoder = _SessionDecoder(self.session_id)
        try:
            async for line in self._response.aiter_lines():
                if self._closed:
                    return
                event = decoder.feed(line)
                if event is not None:
                    yield event
                    if event.event == "closed":
                        return
            if not self._closed:
                raise APIResponseValidationError(
                    "Session stream ended unexpectedly; retrieve session status and billing"
                )
        except APIError as error:
            error.request_id = self._response.headers.get("x-request-id")
            raise
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

    async def __aenter__(self) -> AsyncGenerationSessionStream:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


class GenerationSessions:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        transport: Literal["websocket", "webrtc"],
        billing_mode: Literal["metered"],
        client_request_id: str | None = None,
        max_duration_seconds: int | None = None,
        timeout: float | None = None,
    ) -> GenerationSession:
        body = _create(
            model, transport, billing_mode, client_request_id, max_duration_seconds
        )
        try:
            return _session(
                self._client._request(
                    "POST",
                    "/generation/sessions",
                    body=body,
                    timeout=timeout,
                    max_retries=0,
                ).json()
            )
        except QCloudAIError as error:
            error.client_request_id = body["client_request_id"]
            raise

    def retrieve(self, id: str, *, timeout: float | None = None) -> GenerationSession:
        return _session(
            self._client._request(
                "GET", f"/generation/sessions/{_id(id)}", timeout=timeout
            ).json(),
            id,
        )

    def connect(
        self, id: str, *, timeout: float | None = None
    ) -> GenerationSessionConnection:
        return _connection(
            self._client._request(
                "POST",
                f"/generation/sessions/{_id(id)}/connect",
                timeout=timeout,
                max_retries=0,
            ).json(),
            id,
        )

    def close(self, id: str, *, timeout: float | None = None) -> GenerationSession:
        return _session(
            self._client._request(
                "POST",
                f"/generation/sessions/{_id(id)}/close",
                timeout=timeout,
                max_retries=0,
            ).json(),
            id,
        )

    def offer(
        self,
        id: str,
        *,
        sdp: str,
        session_token: str,
        type: Literal["offer"] = "offer",
        timeout: float | None = None,
    ) -> GenerationSessionStream:
        body = _offer(sdp, type, session_token)
        response = self._client._request(
            "POST",
            f"/generation/sessions/{_id(id)}/offer",
            body=body,
            headers={"X-QCloud-Session-Token": session_token},
            stream=True,
            timeout=timeout,
            max_retries=0,
        )
        return GenerationSessionStream(response, id)


class AsyncGenerationSessions:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        model: str,
        transport: Literal["websocket", "webrtc"],
        billing_mode: Literal["metered"],
        client_request_id: str | None = None,
        max_duration_seconds: int | None = None,
        timeout: float | None = None,
    ) -> GenerationSession:
        body = _create(
            model, transport, billing_mode, client_request_id, max_duration_seconds
        )
        try:
            return _session(
                (
                    await self._client._request(
                        "POST",
                        "/generation/sessions",
                        body=body,
                        timeout=timeout,
                        max_retries=0,
                    )
                ).json()
            )
        except QCloudAIError as error:
            error.client_request_id = body["client_request_id"]
            raise

    async def retrieve(
        self, id: str, *, timeout: float | None = None
    ) -> GenerationSession:
        return _session(
            (
                await self._client._request(
                    "GET", f"/generation/sessions/{_id(id)}", timeout=timeout
                )
            ).json(),
            id,
        )

    async def connect(
        self, id: str, *, timeout: float | None = None
    ) -> GenerationSessionConnection:
        return _connection(
            (
                await self._client._request(
                    "POST",
                    f"/generation/sessions/{_id(id)}/connect",
                    timeout=timeout,
                    max_retries=0,
                )
            ).json(),
            id,
        )

    async def close(
        self, id: str, *, timeout: float | None = None
    ) -> GenerationSession:
        return _session(
            (
                await self._client._request(
                    "POST",
                    f"/generation/sessions/{_id(id)}/close",
                    timeout=timeout,
                    max_retries=0,
                )
            ).json(),
            id,
        )

    async def offer(
        self,
        id: str,
        *,
        sdp: str,
        session_token: str,
        type: Literal["offer"] = "offer",
        timeout: float | None = None,
    ) -> AsyncGenerationSessionStream:
        body = _offer(sdp, type, session_token)
        response = await self._client._request(
            "POST",
            f"/generation/sessions/{_id(id)}/offer",
            body=body,
            headers={"X-QCloud-Session-Token": session_token},
            stream=True,
            timeout=timeout,
            max_retries=0,
        )
        return AsyncGenerationSessionStream(response, id)
