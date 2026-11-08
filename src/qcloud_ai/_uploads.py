"""Origin-bound, single-attempt binary uploads without whole-file buffering."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import stat
import threading
import unicodedata
from collections.abc import AsyncIterable, Iterable
from datetime import datetime
from typing import Any, BinaryIO
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ._exceptions import APIConnectionError, APIError, APIResponseValidationError, APITimeoutError, _raise_for_status
from ._uuid import normalize_uuid
from .types.generation import GenerationUploadedFile

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
CHUNK = 65536
UploadSource = bytes | bytearray | memoryview | str | os.PathLike[str] | BinaryIO | Iterable[bytes]
AsyncUploadSource = bytes | bytearray | memoryview | str | os.PathLike[str] | AsyncIterable[bytes]
_RESERVED = {"content-type", "content-length", "transfer-encoding", "content-encoding", "accept-encoding", "expect", "x-qcloud-filename", "x-qcloud-content-type"}
_CLEANUP_SLOTS = threading.BoundedSemaphore(32)
_CLEANUP_TASKS: set[asyncio.Task[None]] = set()


async def _close_caller_iterator(iterator: Any) -> None:
    """Give cooperative hooks a brief grace period without waiting indefinitely.

    A caller can suppress task cancellation. Limit retained cleanup tasks across
    clients so repeated uploads cannot create an unlimited background backlog.
    SDK-owned files are closed separately even when this budget is exhausted.
    """
    close = getattr(iterator, "aclose", None)
    slots = _CLEANUP_SLOTS
    if not callable(close) or not slots.acquire(blocking=False):
        return
    async def invoke() -> None:
        await close()
    try:
        task = asyncio.create_task(invoke())
    except BaseException:
        slots.release()
        raise
    _CLEANUP_TASKS.add(task)
    def finished(done: asyncio.Task[None]) -> None:
        _CLEANUP_TASKS.discard(done)
        slots.release()
        try:
            done.exception()
        except asyncio.CancelledError:
            pass
    task.add_done_callback(finished)
    try:
        # Unlike wait_for, wait does not await the cancellation of arbitrary code.
        await asyncio.wait({task}, timeout=0.05)
    finally:
        if not task.done():
            task.cancel()


def _positive_size(value: int, name: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")


class UploadInput:
    def __init__(self, source: Any, filename: str | None, content_type: str, size: int | None,
                 max_bytes: int, timeout: float, *, asynchronous: bool = False):
        _positive_size(max_bytes, "max_bytes", MAX_UPLOAD_BYTES)
        if size is not None:
            _positive_size(size, "size", max_bytes)
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(content_type, str) or len(content_type) > 127 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*", content_type):
            raise ValueError("content_type must be a bare MIME type of at most 127 characters")
        content_type = content_type.lower()
        path = os.fspath(source) if isinstance(source, (str, os.PathLike)) else None
        if path is not None and (not isinstance(path, str) or not path or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", path)):
            raise ValueError("source must be a local file path, not a URL")
        self.filename = filename if filename is not None else os.path.basename(path) if path else "upload.bin"
        try:
            valid_name = isinstance(self.filename, str) and 0 < len(self.filename.encode("utf8")) <= 255
        except UnicodeError:
            valid_name = False
        if not valid_name or not self.filename.strip() or self.filename in {".", ".."} or any(c in "/\\" or unicodedata.category(c) == "Cc" for c in self.filename):
            raise ValueError("filename must be a UTF-8 basename of at most 255 bytes without controls")
        self.content_type, self.size, self.max_bytes = content_type, size, max_bytes
        self.source, self.owned, self.iterator = source, None, None
        self.sent, self.complete, self.hash = 0, False, hashlib.sha256()
        try:
            known = None
            if path is not None:
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
                self.owned = os.fdopen(fd, "rb")
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("path must identify a regular file")
                known, self.source = info.st_size, self.owned
            elif isinstance(source, (bytes, bytearray, memoryview)):
                self.source = memoryview(source).cast("B")
                known = len(self.source)
            elif asynchronous:
                if not isinstance(source, AsyncIterable):
                    raise TypeError("async source must be bytes, a path, or an async byte iterable")
            elif not callable(getattr(source, "read", None)) and not isinstance(source, Iterable):
                raise TypeError("source must be bytes, a path, a binary file or a byte iterable")
            if known is not None:
                _positive_size(known, "source length", max_bytes)
                if size is not None and size != known:
                    raise ValueError("size does not match source length")
                self.size = known
        except BaseException:
            if self.owned is not None:
                self.owned.close()
            raise

    def headers(self, defaults: dict[str, str]) -> dict[str, str]:
        headers = {key: value for key, value in defaults.items() if key.lower() not in _RESERVED}
        headers.update({"Content-Type": "application/octet-stream", "Accept-Encoding": "identity", "X-QCloud-Filename": quote(self.filename, safe="~()*!.'-"), "X-QCloud-Content-Type": self.content_type})
        if self.size is not None:
            headers["Content-Length"] = str(self.size)
        return headers

    def slices(self, value: Any):
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("upload streams must yield bytes")
        view = memoryview(value).cast("B")
        if len(view) > self.max_bytes - self.sent or (self.size is not None and len(view) > self.size - self.sent):
            raise ValueError("Upload exceeds its declared size or max_bytes")
        for position in range(0, len(view), CHUNK):
            chunk = bytes(view[position:position + CHUNK])
            self.hash.update(chunk)
            self.sent += len(chunk)
            yield chunk

    def finish(self) -> None:
        if not self.sent or (self.size is not None and self.sent != self.size):
            raise ValueError("Upload is empty or does not match its declared size")
        self.complete = True

    def chunks(self):
        if isinstance(self.source, memoryview):
            yield from self.slices(self.source)
        elif callable(getattr(self.source, "read", None)):
            while True:
                chunk = self.source.read(CHUNK)
                if chunk == b"":
                    break
                yield from self.slices(chunk)
        else:
            self.iterator = iter(self.source)
            for chunk in self.iterator:
                yield from self.slices(chunk)
        self.finish()

    async def achunks(self):
        if isinstance(self.source, memoryview):
            for chunk in self.slices(self.source):
                yield chunk
                await asyncio.sleep(0)
        elif self.owned is not None:
            while True:
                chunk = await asyncio.to_thread(self.owned.read, CHUNK)
                if chunk == b"":
                    break
                for piece in self.slices(chunk):
                    yield piece
        else:
            self.iterator = self.source.__aiter__()
            async for chunk in self.iterator:
                for piece in self.slices(chunk):
                    yield piece
                    await asyncio.sleep(0)
        self.finish()

    def close(self) -> None:
        try:
            if self.iterator is not None and callable(getattr(self.iterator, "close", None)):
                self.iterator.close()
        finally:
            if self.owned is not None:
                self.owned.close()

    async def aclose(self) -> None:
        try:
            if self.iterator is not None:
                await _close_caller_iterator(self.iterator)
        finally:
            if self.owned is not None:
                await asyncio.to_thread(self.owned.close)


def _result(response: httpx.Response, raw: bytes, upload: UploadInput) -> GenerationUploadedFile:
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        data = {"error": {"message": raw.decode("utf8", errors="replace")[:500] or response.reason_phrase}}
    try:
        _raise_for_status(response.status_code, data)
    except APIError as error:
        error.request_id = response.headers.get("x-request-id")
        raise
    try:
        record = data["data"]
        file = GenerationUploadedFile.model_validate(record, strict=True)
        identity = normalize_uuid(file.id, "file ID")
        created = datetime.fromisoformat(file.created_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(file.expires_at.replace("Z", "+00:00"))
        valid = (response.status_code == 201 and upload.complete and file.url == f"qcloud://files/{identity}"
                 and file.filename == upload.filename and file.content_type == upload.content_type
                 and file.size_bytes == upload.sent and file.sha256 == upload.hash.hexdigest()
                 and created.tzinfo is not None and expires.tzinfo is not None and expires > created)
        if not valid:
            raise ValueError("Invalid upload receipt")
        return file
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise APIResponseValidationError("Invalid uploaded file response") from error


def upload_file(client: httpx.Client, base_url: str, headers: dict[str, str], source: UploadSource, *,
                filename: str | None = None, content_type: str = "application/octet-stream", size: int | None = None,
                max_bytes: int = MAX_UPLOAD_BYTES, timeout: float = 120) -> GenerationUploadedFile:
    upload = UploadInput(source, filename, content_type, size, max_bytes, timeout)
    response = None
    try:
        request = client.build_request("POST", base_url + "/generation/files", headers=upload.headers(headers), content=upload.chunks(), timeout=timeout)
        response = client.send(request, stream=True, follow_redirects=False)
        raw = bytearray()
        for chunk in (response.content,) if response.is_stream_consumed else response.iter_raw():
            raw.extend(chunk[:CHUNK - len(raw)])
            if len(raw) == CHUNK:
                if response.is_success:
                    raise APIResponseValidationError("Upload response exceeds 64 KiB")
                break
        return _result(response, bytes(raw), upload)
    except httpx.TimeoutException as error:
        raise APITimeoutError() from error
    except httpx.TransportError as error:
        raise APIConnectionError(cause=error) from error
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            upload.close()


async def async_upload_file(client: httpx.AsyncClient, base_url: str, headers: dict[str, str], source: AsyncUploadSource, *,
                            filename: str | None = None, content_type: str = "application/octet-stream", size: int | None = None,
                            max_bytes: int = MAX_UPLOAD_BYTES, timeout: float = 120) -> GenerationUploadedFile:
    upload = UploadInput(source, filename, content_type, size, max_bytes, timeout, asynchronous=True)
    async def execute():
        response = None
        try:
            request = client.build_request("POST", base_url + "/generation/files", headers=upload.headers(headers), content=upload.achunks(), timeout=timeout)
            response = await client.send(request, stream=True, follow_redirects=False)
            raw = bytearray()
            async def response_chunks():
                if response.is_stream_consumed:
                    yield response.content
                else:
                    async for part in response.aiter_raw():
                        yield part
            async for chunk in response_chunks():
                raw.extend(chunk[:CHUNK - len(raw)])
                if len(raw) == CHUNK:
                    if response.is_success:
                        raise APIResponseValidationError("Upload response exceeds 64 KiB")
                    break
            return _result(response, bytes(raw), upload)
        except httpx.TimeoutException as error:
            raise APITimeoutError() from error
        except httpx.TransportError as error:
            raise APIConnectionError(cause=error) from error
        finally:
            try:
                if response is not None:
                    await response.aclose()
            finally:
                await upload.aclose()
    try:
        return await asyncio.wait_for(execute(), timeout=timeout)
    except asyncio.TimeoutError as error:
        raise APITimeoutError() from error
