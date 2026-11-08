from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from qcloud_ai import (QCloud, AsyncQCloud, APIConnectionError, APIError,
                       APIResponseValidationError, APITimeoutError, PermissionDeniedError)

JOB = "abcdef12-3456-4789-abcd-ef1234567890"
ASSET = "fedcba98-7654-4321-abcd-0123456789ab"
PATH = f"/api/v1/generation/jobs/{JOB}/files/{ASSET}"
PAYLOAD = bytes(n % 256 for n in range(150001))


@pytest.fixture
def files_server():
    state = {"mode": "complete", "requests": 0, "outside": 0, "paths": [], "headers": []}

    class Outside(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            state["outside"] += 1
            self.send_response(200); self.end_headers()

    outside = ThreadingHTTPServer(("127.0.0.1", 0), Outside)
    threading.Thread(target=outside.serve_forever, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            state["requests"] += 1; state["paths"].append(self.path); state["headers"].append(dict(self.headers))
            if state["mode"] == "redirect":
                self.send_response(302); self.send_header("Location", f"http://127.0.0.1:{outside.server_port}/foreign"); self.end_headers(); return
            if state["mode"] == "error":
                data = json.dumps({"error": {"message": "No access"}}).encode()
                self.send_response(403); self.send_header("Content-Length", str(len(data))); self.send_header("X-Request-Id", "req-denied"); self.end_headers(); self.wfile.write(data); return
            if state["mode"] == "large-header":
                self.send_response(200); self.send_header("Content-Length", "9999999"); self.end_headers(); return
            if state["mode"] in ("stall", "truncated"):
                self.send_response(200); self.send_header("Content-Length", "1000000"); self.end_headers()
                self.wfile.write(bytes(65536)); self.wfile.flush()
                if state["mode"] == "stall": time.sleep(0.7)
                self.close_connection = True; return
            data, status = PAYLOAD, 200
            if self.headers.get("Range"):
                assert self.headers["Range"] == "bytes=4-19"
                data, status = PAYLOAD[4:20], 206
            self.send_response(status); self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data))); self.send_header("Accept-Ranges", "bytes"); self.send_header("X-Request-Id", "req-media")
            if status == 206: self.send_header("Content-Range", f"bytes 4-19/{len(PAYLOAD)}")
            self.end_headers(); self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield state, dict(api_key="qc-fixture", organization=JOB, base_url=f"http://127.0.0.1:{server.server_port}/api/v1", max_retries=5)
    server.shutdown(); server.server_close(); outside.shutdown(); outside.server_close()


async def collect(file, asynchronous):
    result = bytearray()
    if asynchronous:
        async with file:
            async for chunk in file:
                assert len(chunk) <= 65536; result.extend(chunk)
    else:
        with file:
            for chunk in file:
                assert len(chunk) <= 65536; result.extend(chunk)
    return bytes(result)


async def invoke(method, asynchronous, *args, **kwargs):
    value = method(*args, **kwargs)
    return await value if asynchronous else value


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_binary_fidelity_headers_ranges_and_identity(files_server, asynchronous):
    state, options = files_server
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        file = await invoke(sdk.generation.files.download, asynchronous, JOB.upper(), ASSET.upper())
        assert file.content_type == "video/mp4" and file.content_length == len(PAYLOAD) and file.request_id == "req-media"
        assert await collect(file, asynchronous) == PAYLOAD
        assert file.bytes_read == len(PAYLOAD) and file._response.is_closed
        with pytest.raises(RuntimeError, match="already been consumed"): await collect(file, asynchronous)
        part = await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET, byte_range="bytes=4-19")
        assert part.status_code == 206 and part.content_range == f"bytes 4-19/{len(PAYLOAD)}"
        assert await collect(part, asynchronous) == PAYLOAD[4:20]
        assert state["paths"] == [PATH, PATH]
        assert all(h["Authorization"] == "Bearer qc-fixture" and h["X-QCloud-Organization"] == JOB and h["Accept-Encoding"] == "identity" for h in state["headers"])
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_typed_errors_no_redirects_no_partial_retries(files_server, asynchronous):
    state, options = files_server
    # Even a caller-supplied redirect-enabled transport cannot forward credentials.
    transport = (httpx.AsyncClient if asynchronous else httpx.Client)(follow_redirects=True)
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options, http_client=transport)
    try:
        state["mode"] = "error"
        with pytest.raises(PermissionDeniedError) as error:
            await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET)
        assert error.value.request_id == "req-denied" and state["requests"] == 1
        state["mode"] = "redirect"
        with pytest.raises(APIError) as error:
            await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET)
        assert error.value.status_code == 302 and state["outside"] == 0 and state["requests"] == 2
        state["mode"] = "truncated"
        file = await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET)
        with pytest.raises(APIConnectionError): await collect(file, asynchronous)
        assert state["requests"] == 3 and file._response.is_closed
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_download_timeout_and_early_close(files_server, asynchronous):
    state, options = files_server
    sdk = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        state["mode"] = "stall"
        file = await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET, timeout=0.15)
        with pytest.raises(APITimeoutError): await collect(file, asynchronous)
        assert file._response.is_closed
        early = await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET)
        if asynchronous:
            async with early:
                async for _ in early: break
        else:
            with early:
                for _ in early: break
        assert early._response.is_closed
        if asynchronous:
            cancelled = await sdk.generation.files.download(JOB, ASSET)
            task = asyncio.create_task(collect(cancelled, True))
            await asyncio.sleep(0.025); task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert cancelled._response.is_closed
    finally:
        await invoke(sdk.close, asynchronous)


class CountedBody(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self): self.produced = 0; self.closed = False
    def __iter__(self):
        for _ in range(10): self.produced += 1; yield bytes(65536)
    async def __aiter__(self):
        for value in self: yield value
    def close(self): self.closed = True
    async def aclose(self): self.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_download_bounds_and_unsafe_input(asynchronous):
    body = CountedBody(); calls = []
    def handler(request): calls.append(request); return httpx.Response(200, stream=body)
    client = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=httpx.MockTransport(handler))
    sdk = (AsyncQCloud if asynchronous else QCloud)(api_key="qc-test", http_client=client)
    try:
        for id in ["https://foreign.invalid/file", "../secret", ASSET + "\n", ASSET.replace("-", "")]:
            with pytest.raises(ValueError): await invoke(sdk.generation.files.download, asynchronous, JOB, id)
        for byte_range in ["bytes=-", "bytes=4-1", "bytes=0-1,4-5", "bytes=0-1\r\nAuthorization:x", "bytes=-0"]:
            with pytest.raises(ValueError): await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET, byte_range=byte_range)
        for max_bytes in [0, -1, 1.5, True, 268435457]:
            with pytest.raises(ValueError): await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET, max_bytes=max_bytes)
        assert not calls
        file = await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET, max_bytes=70000)
        assert body.produced == 0
        with pytest.raises(APIResponseValidationError): await collect(file, asynchronous)
        assert body.produced == 2 and body.closed and len(calls) == 1
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("headers", [{"content-length": "268435457"}, {"content-encoding": "gzip"}, {"content-length": "-1"}])
async def test_download_rejects_invalid_headers_and_closes(asynchronous, headers):
    body = CountedBody()
    client = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers=headers, stream=body)))
    sdk = (AsyncQCloud if asynchronous else QCloud)(api_key="qc-test", http_client=client)
    try:
        with pytest.raises(APIResponseValidationError): await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET)
        assert body.closed and body.produced == 0
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_bounded_malformed_error_diagnostics(asynchronous):
    class ErrorBody(CountedBody):
        def __iter__(self):
            for _ in range(10):
                self.produced += 1
                # Valid deeply nested JSON must still become a typed HTTP error.
                yield b"[" * 2000 + b"]" * 2000 + b" " * (65536 - 4000)
    body = ErrorBody()
    client = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=httpx.MockTransport(lambda request: httpx.Response(403, headers={"x-request-id": "bounded-error"}, stream=body)))
    sdk = (AsyncQCloud if asynchronous else QCloud)(api_key="qc-test", http_client=client)
    try:
        with pytest.raises(PermissionDeniedError) as error:
            await invoke(sdk.generation.files.download, asynchronous, JOB, ASSET)
        assert error.value.request_id == "bounded-error" and len(str(error.value)) < 600
        assert body.produced == 1 and body.closed
    finally:
        await invoke(sdk.close, asynchronous)
