"""Single-use native WebSocket transport. No model codec or media peer is implied."""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import re
import socket as socket_module
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from ._exceptions import APIResponseValidationError, QCloudAIError
from .types.generation import GenerationWebSocketConnection

_PROTOCOL = "qcloud.realtime.v1"
_MAX_BYTES = 16 * 1024 * 1024
_LOG = logging.Logger("qcloud.realtime.private", level=logging.CRITICAL + 1)
_LOG.disabled = True  # Handshake debug logs contain the single-use capability.


class GenerationSocketError(QCloudAIError):
    """Transport failed; inspect session status for authoritative billing."""
    cleanup_error: GenerationSocketCleanupError | None = None


class GenerationSocketClosed(GenerationSocketError):
    """The raw message stream ended normally; this isn't a billing receipt."""


class GenerationSocketCleanupError(QCloudAIError):
    """Socket or HTTP close failed; remote cleanup/billing remains unconfirmed."""

    def __init__(self, session_id: str, *, socket_failed: bool, http_error: BaseException | None):
        self.session_id = session_id
        self.socket_failed = socket_failed
        self.http_error = http_error
        super().__init__("Session cleanup is unconfirmed; retrieve session status and billing")


def _dependency() -> Any:
    try:
        import websockets
    except ImportError:
        raise ImportError('Install qcloud-ai[realtime] to use sessions.open_socket') from None
    if websockets.__version__ != "15.0.1":
        raise ImportError('sessions.open_socket requires websockets==15.0.1; install qcloud-ai[realtime]')
    return websockets


def _origin(value: str, *, bare: bool = False) -> tuple[str, str, int]:
    if not isinstance(value, str) or re.search(r"[\s\\?#\x00-\x1f\x7f]", value):
        raise ValueError("Invalid realtime origin")
    url = urlsplit(value)
    if (url.scheme not in ("https", "http", "wss", "ws") or not url.hostname
            or url.username is not None or url.password is not None or url.query or url.fragment
            or (bare and url.path not in ("", "/"))):
        raise ValueError("Realtime origin must be a bare trusted HTTP(S) or WS(S) origin")
    secure = url.scheme in ("https", "wss")
    if not secure and url.hostname not in ("127.0.0.1", "::1"):
        raise ValueError("Insecure realtime connections require a literal loopback address")
    port = url.port if url.port is not None else (443 if secure else 80)
    if port == 0 or url.netloc.endswith(":"):
        raise ValueError("Invalid realtime port")
    return ("wss" if secure else "ws", url.hostname.lower(), port)


def _options(base_url: str, relay_origin: str | None, open_timeout: float, close_timeout: float, send_timeout: float,
             max_message_bytes: int, max_queue: int, max_duration_seconds: float) -> tuple[str, str, int]:
    for value in (open_timeout, close_timeout, send_timeout):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 60:
            raise ValueError("Socket timeouts must be finite seconds in (0, 60]")
    if isinstance(max_message_bytes, bool) or not isinstance(max_message_bytes, int) or not 1 <= max_message_bytes <= _MAX_BYTES:
        raise ValueError("max_message_bytes must be an integer from 1 to 16777216")
    if isinstance(max_queue, bool) or not isinstance(max_queue, int) or not 1 <= max_queue <= 16:
        raise ValueError("max_queue must be an integer from 1 to 16")
    if isinstance(max_duration_seconds, bool) or not isinstance(max_duration_seconds, (int, float)) or not math.isfinite(max_duration_seconds) or not 0 < max_duration_seconds <= 3600:
        raise ValueError("max_duration_seconds must be finite seconds in (0, 3600]")
    return _origin(relay_origin, bare=True) if relay_origin is not None else _origin(base_url)


def _capability(value: Any, session_id: str, base_url: str, origin: tuple[str, str, int]) -> tuple[str, list[str], str]:
    try:
        if not isinstance(value, GenerationWebSocketConnection) or value.session_id != session_id:
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value.token):
            raise ValueError()
        raw = base64.urlsafe_b64decode(value.token + "=")
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != value.token:
            raise ValueError()
        if value.subprotocols != [_PROTOCOL, "qcloud.cap." + value.token]:
            raise ValueError()
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value.expires_at):
            raise ValueError()
        ttl = (datetime.fromisoformat(value.expires_at.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
        if not 0 < ttl <= 60 or value.encoding not in ("json", "msgpack"):
            raise ValueError()
        url = urlsplit(value.websocket_url)
        paths = {f"/v1/generation/sessions/{session_id}/socket",
                 urlsplit(base_url).path.rstrip("/") + f"/generation/sessions/{session_id}/socket"}
        if url.scheme not in ("ws", "wss") or _origin(value.websocket_url) != origin or url.path not in paths:
            raise ValueError()
        return value.websocket_url, list(value.subprotocols), value.encoding
    except (ValueError, TypeError, OverflowError):
        raise APIResponseValidationError("Invalid native WebSocket capability, expiry, route or trusted origin") from None


def _message(value: str | bytes, limit: int) -> None:
    if not isinstance(value, (str, bytes)):
        raise TypeError("send accepts raw str or bytes; encode the model's schema explicitly")
    if len(value) > limit or (isinstance(value, str) and len(value.encode("utf-8")) > limit):
        raise ValueError("Socket message exceeds max_message_bytes")


def _attach(error: BaseException, cleanup: GenerationSocketCleanupError | None) -> None:
    if cleanup is not None:
        error.cleanup_error = cleanup  # type: ignore[attr-defined]


class GenerationSocket:
    """Raw str/bytes context manager and iterator. close() also requests HTTP close once."""
    def __init__(self, sessions: Any, session_id: str, timeout: float, limit: int, send_timeout: float):
        self.session_id, self.encoding = session_id, ""
        self.close_result: Any = None
        self.cleanup_error: GenerationSocketCleanupError | None = None
        self._sessions, self._timeout, self._limit = sessions, timeout, limit
        self._send_timeout = send_timeout
        self._socket: Any = None
        self._closed = False
        self._timer: threading.Timer | None = None
        self._close_lock, self._send_lock = threading.Lock(), threading.Lock()

    def _finish(self, error: BaseException) -> None:
        try:
            self.close()
        except GenerationSocketCleanupError:
            _attach(error, self.cleanup_error)

    def _abort_transport(self) -> None:
        # websockets 15.0.1 holds protocol_mutex across blocking sendall().
        # close() takes that mutex too. Shutdown must happen independently of
        # both locks, before the library can finish releasing its own threads.
        if self._socket is not None:
            try:
                self._socket.socket.shutdown(socket_module.SHUT_RDWR)
            except OSError:
                pass
            self._socket.socket.close()

    def send(self, data: str | bytes) -> None:
        _message(data, self._limit)
        if self._closed:
            raise GenerationSocketClosed("Session socket is closed")
        if not self._send_lock.acquire(blocking=False):
            raise GenerationSocketError("Only one send may be in flight")
        timer = threading.Timer(self._send_timeout, self._abort_transport)
        timer.daemon = True
        timer.start()
        try:
            self._socket.send(data)
        except Exception:
            error = GenerationSocketError("Socket send failed; frames were not replayed")
            self._finish(error)
            raise error from None
        finally:
            timer.cancel()
            self._send_lock.release()

    def recv(self, *, timeout: float | None = None) -> str | bytes:
        if self._closed:
            self.close()
            raise GenerationSocketClosed("Session socket is closed")
        from websockets.exceptions import ConnectionClosedOK
        try:
            message = self._socket.recv(timeout=timeout)
        except ConnectionClosedOK:
            self.close()
            raise GenerationSocketClosed("Session message stream ended") from None
        except Exception:
            error = GenerationSocketError("Socket receive failed; connection was not retried")
            self._finish(error)
            raise error from None
        if self._closed:
            self.close()
            raise GenerationSocketClosed("Session socket is closed")
        return message

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                if self.cleanup_error:
                    raise self.cleanup_error
                return
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
            socket_failed, http_error = False, None
            aborted = threading.Event()
            def abort() -> None:
                aborted.set()
                self._abort_transport()
            watchdog = threading.Timer(self._timeout, abort)
            watchdog.daemon = True
            watchdog.start()
            try:
                if self._socket is not None:
                    self._socket.close()
                    socket_failed = self._socket.close_code in (None, 1006)
            except Exception:
                socket_failed = True
                self._abort_transport()
            finally:
                watchdog.cancel()
                socket_failed = socket_failed or aborted.is_set()
            try:
                self.close_result = self._sessions.close(self.session_id, timeout=self._timeout)
            except Exception as error:
                http_error = error
            if socket_failed or http_error is not None:
                self.cleanup_error = GenerationSocketCleanupError(self.session_id, socket_failed=socket_failed, http_error=http_error)
                raise self.cleanup_error

    def _expire(self) -> None:
        try:
            self.close()
        except GenerationSocketCleanupError:
            pass  # Retained on cleanup_error and raised by subsequent close/recv.

    def __iter__(self) -> GenerationSocket:
        return self

    def __next__(self) -> str | bytes:
        try:
            return self.recv()
        except GenerationSocketClosed:
            raise StopIteration from None

    def __enter__(self) -> GenerationSocket:
        return self

    def __exit__(self, _type: Any, error: BaseException | None, _tb: Any) -> None:
        if error is None:
            self.close()
        else:
            self._finish(error)


class AsyncGenerationSocket:
    """Async raw-message context/iterator. Cancellation closes both transports."""
    def __init__(self, sessions: Any, session_id: str, timeout: float, limit: int, send_timeout: float):
        self.session_id, self.encoding = session_id, ""
        self.close_result: Any = None
        self.cleanup_error: GenerationSocketCleanupError | None = None
        self._sessions, self._timeout, self._limit = sessions, timeout, limit
        self._send_timeout = send_timeout
        self._socket: Any = None
        self._close_task: asyncio.Task[None] | None = None
        self._sending = False
        self._timer: asyncio.TimerHandle | None = None

    async def _finish(self, error: BaseException) -> None:
        try:
            await self.aclose()
        except GenerationSocketCleanupError:
            _attach(error, self.cleanup_error)

    async def send(self, data: str | bytes) -> None:
        _message(data, self._limit)
        if self._close_task is not None:
            raise GenerationSocketClosed("Session socket is closed")
        if self._sending:
            raise GenerationSocketError("Only one send may be in flight")
        self._sending = True
        try:
            await asyncio.wait_for(self._socket.send(data), self._send_timeout)
        except asyncio.CancelledError as error:
            await self._finish(error)
            raise
        except Exception:
            error = GenerationSocketError("Socket send failed; frames were not replayed")
            await self._finish(error)
            raise error from None
        finally:
            self._sending = False

    async def recv(self) -> str | bytes:
        if self._close_task is not None:
            await self.aclose()
            raise GenerationSocketClosed("Session socket is closed")
        from websockets.exceptions import ConnectionClosedOK
        try:
            message = await self._socket.recv()
        except ConnectionClosedOK:
            await self.aclose()
            raise GenerationSocketClosed("Session message stream ended") from None
        except asyncio.CancelledError as error:
            await self._finish(error)
            raise
        except Exception:
            error = GenerationSocketError("Socket receive failed; connection was not retried")
            await self._finish(error)
            raise error from None
        if self._close_task is not None:
            await self.aclose()
            raise GenerationSocketClosed("Session socket is closed")
        return message

    async def _cleanup(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        socket_failed, http_error = False, None
        try:
            if self._socket is not None:
                await asyncio.wait_for(self._socket.close(), self._timeout)
                socket_failed = self._socket.close_code in (None, 1006)
        except Exception:
            socket_failed = True
            # External wait_for cancellation can precede the library's own
            # close deadline; force local closure even in that timing window.
            if self._socket is not None:
                self._socket.transport.abort()
        try:
            self.close_result = await asyncio.wait_for(self._sessions.close(self.session_id, timeout=self._timeout), self._timeout)
        except Exception as error:
            http_error = error
        if socket_failed or http_error is not None:
            self.cleanup_error = GenerationSocketCleanupError(self.session_id, socket_failed=socket_failed, http_error=http_error)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._cleanup())
        cancelled = None
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError as error:
                cancelled = error
        self._close_task.result()
        if cancelled is not None:
            _attach(cancelled, self.cleanup_error)
            raise cancelled
        if self.cleanup_error is not None:
            raise self.cleanup_error

    async def close(self) -> None:
        await self.aclose()

    def __aiter__(self) -> AsyncGenerationSocket:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return await self.recv()
        except GenerationSocketClosed:
            raise StopAsyncIteration from None

    async def __aenter__(self) -> AsyncGenerationSocket:
        return self

    async def __aexit__(self, _type: Any, error: BaseException | None, _tb: Any) -> None:
        if error is None:
            await self.aclose()
        else:
            await self._finish(error)


def open_socket(sessions: Any, session_id: str, *, relay_origin: str | None = None,
                open_timeout: float = 10, close_timeout: float = 5, send_timeout: float = 10,
                max_message_bytes: int = _MAX_BYTES, max_queue: int = 4,
                max_duration_seconds: float = 3600) -> GenerationSocket:
    origin = _options(sessions._client.base_url, relay_origin, open_timeout, close_timeout, send_timeout, max_message_bytes, max_queue, max_duration_seconds)
    _dependency()
    from websockets.sync.client import connect
    capability = sessions.connect(session_id, timeout=open_timeout)
    result = GenerationSocket(sessions, session_id, close_timeout, max_message_bytes, send_timeout)
    try:
        url, protocols, result.encoding = _capability(capability, session_id, sessions._client.base_url, origin)
        result._socket = connect(url, subprotocols=protocols, proxy=None, compression=None, logger=_LOG,
                                 open_timeout=open_timeout, close_timeout=close_timeout, max_size=max_message_bytes, max_queue=max_queue)
        if result._socket.subprotocol != _PROTOCOL:
            raise APIResponseValidationError("Realtime subprotocol was not negotiated")
        result._timer = threading.Timer(max_duration_seconds, result._expire)
        result._timer.daemon = True
        result._timer.start()
        return result
    except BaseException as original:
        error = original if isinstance(original, (APIResponseValidationError, KeyboardInterrupt, SystemExit)) else GenerationSocketError("Socket handshake failed; capability was not retried")
        result._finish(error)
        raise error from None


async def async_open_socket(sessions: Any, session_id: str, *, relay_origin: str | None = None,
                            open_timeout: float = 10, close_timeout: float = 5, send_timeout: float = 10,
                            max_message_bytes: int = _MAX_BYTES, max_queue: int = 4,
                            max_duration_seconds: float = 3600) -> AsyncGenerationSocket:
    origin = _options(sessions._client.base_url, relay_origin, open_timeout, close_timeout, send_timeout, max_message_bytes, max_queue, max_duration_seconds)
    _dependency()
    from websockets.asyncio.client import connect

    class NoRedirectConnect(connect):
        def process_redirect(self, exc: Exception) -> Exception:
            return exc

    capability = await sessions.connect(session_id, timeout=open_timeout)
    result = AsyncGenerationSocket(sessions, session_id, close_timeout, max_message_bytes, send_timeout)
    try:
        url, protocols, result.encoding = _capability(capability, session_id, sessions._client.base_url, origin)
        result._socket = await NoRedirectConnect(url, subprotocols=protocols, proxy=None, compression=None, logger=_LOG,
            open_timeout=open_timeout, close_timeout=close_timeout, max_size=max_message_bytes, max_queue=max_queue, write_limit=32768)
        if result._socket.subprotocol != _PROTOCOL:
            raise APIResponseValidationError("Realtime subprotocol was not negotiated")
        def expire() -> None:
            if result._close_task is None:
                result._close_task = asyncio.create_task(result._cleanup())
        result._timer = asyncio.get_running_loop().call_later(max_duration_seconds, expire)
        return result
    except BaseException as original:
        error = original if isinstance(original, (APIResponseValidationError, asyncio.CancelledError, KeyboardInterrupt, SystemExit)) else GenerationSocketError("Socket handshake failed; capability was not retried")
        await result._finish(error)
        raise error from None
