import asyncio
import hashlib
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import httpx
import pytest

from qcloud_ai import (QCloud, AsyncQCloud, PermissionDeniedError, RateLimitError,
                       APIError, APIConnectionError, APITimeoutError, APIResponseValidationError)

IDENTITY = "abcdef12-3456-4789-abcd-ef1234567890"
PAYLOAD = bytes(i % 256 for i in range(150001))


def receipt(body, filename="upload.bin", content_type="application/octet-stream"):
    return {"data": {"id": IDENTITY, "object": "generation.file", "url": f"qcloud://files/{IDENTITY}",
                     "filename": filename, "content_type": content_type, "size_bytes": len(body),
                     "sha256": hashlib.sha256(body).hexdigest(), "created_at": "2026-11-08T00:00:00Z", "expires_at": "2026-11-09T00:00:00Z"}}


@pytest.fixture
def upload_server():
    state = {"mode": "normal", "requests": 0, "body": b"", "headers": {}}
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args): pass
        def do_POST(self):
            state["requests"] += 1
            state["headers"] = dict(self.headers)
            self.connection.settimeout(2)
            try:
                if self.headers.get("Transfer-Encoding") == "chunked":
                    chunks = []
                    while True:
                        length = int(self.rfile.readline().strip(), 16)
                        if length == 0:
                            self.rfile.readline()
                            break
                        chunks.append(self.rfile.read(length))
                        self.rfile.read(2)
                    body = b"".join(chunks)
                else:
                    body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                state["body"] = body
                assert self.path == "/api/v1/generation/files"
                assert self.headers.get("Authorization") == "Bearer qc-fixture"
                if state["mode"] == "disconnect":
                    self.close_connection = True
                    return
                if state["mode"] == "redirect":
                    self.send_response(307)
                    self.send_header("Location", "https://outside.invalid/private")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if state["mode"] == "stall":
                    self.send_response(201)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.write(b"{"); self.wfile.flush(); time.sleep(0.4)
                    self.close_connection = True
                    return
                status = 403 if state["mode"] in {"error", "huge-error"} else 429 if state["mode"] == "rate" else 201
                result = receipt(body, unquote(self.headers["X-QCloud-Filename"]), self.headers["X-QCloud-Content-Type"])
                if state["mode"] == "foreign": result["data"]["url"] = "https://outside.invalid/private"
                if state["mode"] == "wrong-size": result["data"]["size_bytes"] += 1
                if state["mode"] == "wrong-hash": result["data"]["sha256"] = "0" * 64
                if status != 201: result = {"error": {"message": "Upload refused"}}
                payload = b"x" * 200000 if state["mode"] == "huge-error" else json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-Request-ID", "upload-fixture")
                self.end_headers(); self.wfile.write(payload)
            except (OSError, ValueError):
                self.close_connection = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield state, {"api_key": "qc-fixture", "base_url": f"http://127.0.0.1:{server.server_port}/api/v1", "organization": IDENTITY, "max_retries": 5}
    server.shutdown(); server.server_close(); thread.join()


async def call(client, asynchronous, source, **options):
    value = client.generation.files.upload(source, **options)
    return await value if asynchronous else value


async def close(client, asynchronous):
    if asynchronous: await client.close()
    else: client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_exact_binary_metadata_paths_and_streams(upload_server, tmp_path, asynchronous):
    state, options = upload_server
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        file = await call(sdk, asynchronous, PAYLOAD, filename="φωνή.wav", content_type="audio/wav")
        assert file.url == f"qcloud://files/{IDENTITY}" and file.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
        assert state["body"] == PAYLOAD and state["headers"]["Content-Type"] == "application/octet-stream"
        assert state["headers"]["Content-Length"] == str(len(PAYLOAD)) and state["headers"]["X-QCloud-Organization"] == IDENTITY
        assert unquote(state["headers"]["X-QCloud-Filename"]) == "φωνή.wav"
        assert (await call(sdk, asynchronous, PAYLOAD, content_type="Image/PNG")).content_type == "image/png"
        assert state["headers"]["X-QCloud-Content-Type"] == "image/png"
        boundary_mime = "image/" + "x" * 121
        assert (await call(sdk, asynchronous, PAYLOAD, filename="é" * 127 + "a", content_type=boundary_mime)).content_type == boundary_mime
        path = tmp_path / "input.bin"; path.write_bytes(PAYLOAD)
        assert (await call(sdk, asynchronous, path)).filename == "input.bin"
        assert state["body"] == PAYLOAD
        async def async_source():
            yield PAYLOAD[:17]
            yield PAYLOAD[17:]
        source = async_source() if asynchronous else iter([PAYLOAD[:17], PAYLOAD[17:]])
        await call(sdk, asynchronous, source)
        assert state["body"] == PAYLOAD and state["headers"]["Transfer-Encoding"] == "chunked"
        if not asynchronous:
            source_file = io.BytesIO(PAYLOAD)
            await call(sdk, False, source_file)
            assert not source_file.closed and source_file.tell() == len(PAYLOAD)
    finally:
        await close(sdk, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_preflight_rejects_urls_unsafe_metadata_empty_and_invalid_limits(upload_server, asynchronous):
    state, options = upload_server
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        for source in ["https://outside.invalid/file", b"", object()]:
            with pytest.raises((ValueError, TypeError)): await call(sdk, asynchronous, source)
        for filename in ["../file", "a/b", "a\\b", ".", "..", "", "   ", "\u2003", "bad\n", "bad\x7f", "bad\x85", "x" * 256, "é" * 128, "\ud800"]:
            with pytest.raises(ValueError): await call(sdk, asynchronous, PAYLOAD, filename=filename)
        for content_type in ["image", "image/png\n", "image/png; charset=utf8", "!image/png", "image/!png", "image/" + "x" * 122]:
            with pytest.raises(ValueError): await call(sdk, asynchronous, PAYLOAD, content_type=content_type)
        for max_bytes in [0, -1, True, float("inf"), 268435457]:
            with pytest.raises(ValueError): await call(sdk, asynchronous, PAYLOAD, max_bytes=max_bytes)
        with pytest.raises(ValueError): await call(sdk, asynchronous, PAYLOAD, size=1)
        assert state["requests"] == 0
    finally:
        await close(sdk, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_error_types_no_retry_redirect_and_bounded_diagnostics(upload_server, asynchronous):
    state, options = upload_server
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        for mode, error in [("error", PermissionDeniedError), ("rate", RateLimitError), ("redirect", APIError), ("disconnect", APIConnectionError), ("huge-error", PermissionDeniedError)]:
            before = state["requests"]; state["mode"] = mode
            with pytest.raises(error) as found: await call(sdk, asynchronous, PAYLOAD)
            assert state["requests"] == before + 1
            if mode in {"error", "huge-error"}: assert found.value.request_id == "upload-fixture"
            if mode == "huge-error": assert len(str(found.value)) < 600
    finally:
        await close(sdk, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_receipt_identity_size_hash_and_timeout(upload_server, asynchronous):
    state, options = upload_server
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        for mode in ["foreign", "wrong-size", "wrong-hash"]:
            state["mode"] = mode
            with pytest.raises(APIResponseValidationError): await call(sdk, asynchronous, PAYLOAD)
        state["mode"] = "stall"
        with pytest.raises(APITimeoutError): await call(sdk, asynchronous, PAYLOAD, timeout=0.05)
    finally:
        await close(sdk, asynchronous)


class CaptureTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    def __init__(self): self.calls = 0
    def validate(self, request, chunks):
        self.calls += 1
        assert request.headers["Content-Type"] == "application/octet-stream"
        assert request.headers["Content-Length"] == str(len(PAYLOAD))
        assert "Transfer-Encoding" not in request.headers
        assert all(len(chunk) <= 65536 for chunk in chunks)
        return httpx.Response(201, json=receipt(b"".join(chunks)))
    def handle_request(self, request): return self.validate(request, list(request.stream))
    async def handle_async_request(self, request): return self.validate(request, [chunk async for chunk in request.stream])


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_stream_length_limits_empty_stream_and_generator_cleanup(upload_server, asynchronous):
    _, options = upload_server
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        for settings in [{"max_bytes": 100}, {"size": 100}, {"size": len(PAYLOAD) + 1}, {}]:
            stopped = []
            def sync_source():
                try:
                    if settings:
                        yield PAYLOAD
                finally:
                    stopped.append(True)
            async def async_source():
                try:
                    if settings:
                        yield PAYLOAD
                finally:
                    stopped.append(True)
            with pytest.raises(ValueError, match="size|max_bytes|empty"):
                await call(sdk, asynchronous, async_source() if asynchronous else sync_source(), **settings)
            assert stopped == [True]
    finally:
        await close(sdk, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_chunk_bounds_and_reserved_header_overrides(asynchronous):
    transport = CaptureTransport()
    http = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=transport)
    sdk = (AsyncQCloud if asynchronous else QCloud)(api_key="fixture", http_client=http, default_headers={"content-type": "application/json", "Content-Length": "1", "transfer-encoding": "chunked"})
    try:
        await call(sdk, asynchronous, PAYLOAD)
        assert transport.calls == 1
    finally:
        await close(sdk, asynchronous)


@pytest.mark.asyncio
async def test_async_cancellation_stops_pending_source_and_closes_iterator(upload_server):
    _, options = upload_server
    sdk = AsyncQCloud(**options)
    started, stopped = asyncio.Event(), asyncio.Event()
    async def source():
        try:
            yield PAYLOAD[:100]
            started.set()
            await asyncio.Event().wait()
        finally:
            stopped.set()
    try:
        pending = asyncio.create_task(sdk.generation.files.upload(source()))
        await asyncio.wait_for(started.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        assert stopped.is_set()
    finally:
        await sdk.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_cancel", [False, True])
async def test_async_deadline_and_cancellation_do_not_wait_for_blocked_aclose(caller_cancel):
    waiting, closing, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Source:
        first = True
        def __aiter__(self): return self
        async def __anext__(self):
            if self.first:
                self.first = False
                return PAYLOAD[:1024]
            waiting.set()
            await asyncio.Event().wait()
        async def aclose(self):
            closing.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            async for _ in request.stream:
                pass
            raise AssertionError("Incomplete source must never finish")
    async with AsyncQCloud(api_key="fixture", http_client=httpx.AsyncClient(transport=Transport())) as sdk:
        pending = asyncio.create_task(sdk.generation.files.upload(Source(), timeout=10 if caller_cancel else 0.03))
        await asyncio.wait_for(waiting.wait(), 1)
        if caller_cancel:
            pending.cancel()
        with pytest.raises(asyncio.CancelledError if caller_cancel else APITimeoutError):
            await asyncio.wait_for(pending, 0.5)
        assert closing.is_set()
        await asyncio.wait_for(cancelled.wait(), 0.5)


@pytest.mark.asyncio
async def test_noncooperative_cleanup_backlog_is_bounded_and_preserves_http_error(monkeypatch):
    import qcloud_ai._uploads as uploads
    monkeypatch.setattr(uploads, "_CLEANUP_SLOTS", threading.BoundedSemaphore(2))
    release = asyncio.Event()
    started, stopped = [], []
    class Source:
        def __aiter__(self): return self
        async def __anext__(self): return PAYLOAD[:1024]
        async def aclose(self):
            started.append(True)
            try:
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        pass
            finally:
                stopped.append(True)
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            async for _ in request.stream:
                break
            return httpx.Response(403, json={"error": {"message": "denied"}}, headers={"x-request-id": "cleanup-budget"})
    try:
        async with AsyncQCloud(api_key="fixture", http_client=httpx.AsyncClient(transport=Transport())) as sdk:
            for _ in range(3):
                with pytest.raises(PermissionDeniedError) as error:
                    await asyncio.wait_for(sdk.generation.files.upload(Source()), 0.5)
                assert error.value.request_id == "cleanup-budget"
        assert len(started) == 2
    finally:
        release.set()
        for _ in range(100):
            if len(stopped) == len(started):
                break
            await asyncio.sleep(0.001)
        assert len(stopped) == len(started)
