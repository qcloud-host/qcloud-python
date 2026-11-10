"""Real loopback HTTP and WebSocket fixtures; never call a provider."""
from __future__ import annotations

import asyncio
import base64
import json
import hashlib
import socket
import socketserver
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response
from websockets.datastructures import Headers
from websockets.sync.server import serve

from qcloud_ai import (APIResponseValidationError, AsyncQCloud, GenerationSocketCleanupError,
                       GenerationSocketError, QCloud)


@pytest.fixture
def socket_server():
    id = str(uuid4())
    token = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    state = {"connect": 0, "close": 0, "handshakes": [], "messages": [], "mode": "echo", "override": {}, "close_status": 200}

    def handshake(connection, request):
        state["handshakes"].append((request.path, dict(request.headers)))
        if state["mode"] == "slow_handshake":
            time.sleep(0.2)
        if state["mode"] == "redirect":
            return Response(302, "Found", Headers({"Location": state["url"], "Content-Length": "0"}), b"")
        return None

    def handle(connection):
        try:
            if state["mode"] == "oversize":
                connection.send("世" * 100)
            elif state["mode"] == "abnormal":
                connection.close(code=1011, reason="fixture")
            else:
                for message in connection:
                    state["messages"].append(message)
                    connection.send(message)
                    if state["mode"] == "finish":
                        connection.close()
        except ConnectionClosed:
            pass

    with serve(handle, "127.0.0.1", 0, process_request=handshake, subprotocols=["qcloud.realtime.v1"]) as websocket:
        thread = threading.Thread(target=websocket.serve_forever, daemon=True)
        thread.start()
        port = websocket.socket.getsockname()[1]
        state["url"] = f"ws://127.0.0.1:{port}/v1/generation/sessions/{id}/socket"
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                assert self.headers["Authorization"] == "Bearer qc-fixture"
                if self.path.endswith("/connect"):
                    state["connect"] += 1
                    data = {"transport": "websocket", "session_id": id, "websocket_url": state["url"],
                            "token": token, "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
                            "subprotocols": ["qcloud.realtime.v1", "qcloud.cap." + token], "encoding": "msgpack", **state["override"]}
                    status = 201
                else:
                    assert self.path == f"/v1/generation/sessions/{id}/close"
                    state["close"] += 1
                    if state["mode"] == "slow_close":
                        time.sleep(0.2)
                    status = state["close_status"]
                    data = {"object": "generation.session", "id": id, "model": "qcloud/fixture", "transport": "websocket", "status": "closed",
                            "created_at": "now", "updated_at": "now", "connected_at": None, "completed_at": None, "deadline_at": None,
                            "expires_at": "later", "max_duration_seconds": 30, "close_requested": True, "error": None,
                            "billing": {"mode": "metered", "status": "pending", "currency": "USD", "markup_multiplier": 1.2, "cost_usd": None}, "license": None}
                body = json.dumps({"data": data} if status < 400 else {"error": {"message": "fixture close failed"}}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        http_thread = threading.Thread(target=http.serve_forever, daemon=True)
        http_thread.start()
        yield id, state, {"api_key": "qc-fixture", "base_url": f"http://127.0.0.1:{http.server_port}/v1", "max_retries": 4,
                          "default_headers": {"X-Private-Fixture": "private"}}, {"relay_origin": f"ws://127.0.0.1:{port}"}
        http.shutdown()
        http.server_close()
        http_thread.join(timeout=5)
        websocket.shutdown()
        thread.join(timeout=5)


async def invoke(asynchronous, method, *args, **kwargs):
    result = method(*args, **kwargs)
    return await result if asynchronous else result


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_raw_unicode_and_binary_no_credentials_no_reconnect(socket_server, asynchronous, monkeypatch):
    id, state, options, socket_options = socket_server
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    # The HTTP client has its own proxy policy. Keep the loopback capability
    # request direct so this assertion tests the socket's explicit proxy=None.
    http_client = (httpx.AsyncClient if asynchronous else httpx.Client)(trust_env=False)
    client = (AsyncQCloud if asynchronous else QCloud)(**options, http_client=http_client)
    try:
        stream = await invoke(asynchronous, client.generation.sessions.open_socket, id.upper(), **socket_options)
        assert stream.session_id == id and stream.encoding == "msgpack"
        for value in ['{"text":"Γεια 🌍"}', b"\x81\xa4data\xc4\x02\x00\xff"]:
            await invoke(asynchronous, stream.send, value)
            assert await invoke(asynchronous, stream.recv) == value
        await invoke(asynchronous, stream.close)
        await invoke(asynchronous, stream.close)
        assert stream.close_result.id == id
        assert stream.close_result.billing.status == "pending"  # Not reported settled.
        assert state["connect"] == state["close"] == len(state["handshakes"]) == 1
        path, headers = state["handshakes"][0]
        assert path == f"/v1/generation/sessions/{id}/socket"
        assert not {"authorization", "x-private-fixture", "cookie"} & {name.lower() for name in headers}
        assert state["messages"] == ['{"text":"Γεια 🌍"}', b"\x81\xa4data\xc4\x02\x00\xff"]
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("kind", ["expired", "future", "origin", "route", "query", "token", "protocol", "identity", "webrtc"])
async def test_capability_boundaries_before_socket(socket_server, asynchronous, kind):
    id, state, options, socket_options = socket_server
    changes = {"expired": {"expires_at": "2020-01-01T00:00:00Z"},
               "future": {"expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()},
               "origin": {"websocket_url": "wss://foreign.invalid/v1/generation/sessions/" + id + "/socket"},
               "route": {"websocket_url": state["url"] + "/extra"}, "query": {"websocket_url": state["url"] + "?"},
               "token": {"token": "x" * 43}, "protocol": {"subprotocols": ["qcloud.realtime.v1"]},
               "identity": {"session_id": None}, "webrtc": {"transport": "webrtc", "signaling": "websocket", "protocol": "rtc-signaling-v1"}}
    state["override"] = changes[kind]
    client = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        with pytest.raises(APIResponseValidationError):
            await invoke(asynchronous, client.generation.sessions.open_socket, id, **socket_options)
        assert state["connect"] == state["close"] == 1
        assert state["handshakes"] == []
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_unparsed_capability_does_not_claim_socket_ownership(socket_server, asynchronous):
    id, state, options, socket_options = socket_server
    state["override"] = {"session_id": str(uuid4())}
    client = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        with pytest.raises(APIResponseValidationError):
            await invoke(asynchronous, client.generation.sessions.open_socket, id, **socket_options)
        assert state["connect"] == 1 and state["close"] == 0
        assert state["handshakes"] == []
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("mode", ["redirect", "abnormal", "oversize"])
async def test_transport_failure_cleanup_once(socket_server, asynchronous, mode):
    id, state, options, socket_options = socket_server
    state["mode"] = mode
    client = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        with pytest.raises(GenerationSocketError):
            stream = await invoke(asynchronous, client.generation.sessions.open_socket, id, max_message_bytes=64, max_queue=1, **socket_options)
            await invoke(asynchronous, stream.recv)
        assert state["connect"] == state["close"] == len(state["handshakes"]) == 1
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_close_failure_distinct_from_transport_failure(socket_server, asynchronous):
    id, state, options, socket_options = socket_server
    state.update(mode="abnormal", close_status=503)
    client = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        stream = await invoke(asynchronous, client.generation.sessions.open_socket, id, **socket_options)
        with pytest.raises(GenerationSocketError) as caught:
            await invoke(asynchronous, stream.recv)
        assert isinstance(caught.value.cleanup_error, GenerationSocketCleanupError)
        assert caught.value.cleanup_error.http_error.status_code == 503
        with pytest.raises(GenerationSocketCleanupError):
            await invoke(asynchronous, stream.close)
        assert state["close"] == 1
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
async def test_cancel_recv_completes_cleanup_and_preserves_cancellation(socket_server):
    id, state, options, socket_options = socket_server
    state["close_status"] = 503
    async with AsyncQCloud(**options) as client:
        stream = await client.generation.sessions.open_socket(id, **socket_options)
        task = asyncio.create_task(stream.recv())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        # Python 3.10 can replace CancelledError at the Task await boundary.
        # The socket is the stable carrier even when custom exception attributes
        # are not preserved by asyncio.
        assert isinstance(stream.cleanup_error, GenerationSocketCleanupError)
        assert stream.cleanup_error.http_error.status_code == 503
        if hasattr(caught.value, "cleanup_error"):
            assert caught.value.cleanup_error is stream.cleanup_error
        assert state["close"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("during", ["handshake", "close"])
async def test_cancellation_during_open_or_close_keeps_single_cleanup(socket_server, during):
    id, state, options, socket_options = socket_server
    async with AsyncQCloud(**options) as client:
        if during == "handshake":
            state["mode"] = "slow_handshake"
            task = asyncio.create_task(client.generation.sessions.open_socket(id, **socket_options))
        else:
            stream = await client.generation.sessions.open_socket(id, **socket_options)
            state["mode"] = "slow_close"
            task = asyncio.create_task(stream.aclose())
        def started():
            return bool(state["handshakes"]) if during == "handshake" else state["close"] == 1
        async def wait_started():
            while not started():
                await asyncio.sleep(0.005)
        await asyncio.wait_for(wait_started(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert state["connect"] == state["close"] == 1
        if during == "close":
            await stream.aclose()
            assert stream.close_result.id == id
            assert state["close"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_context_body_error_survives_close_failure_and_send_bounds(socket_server, asynchronous):
    id, state, options, socket_options = socket_server
    state["close_status"] = 503
    client = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        stream = await invoke(asynchronous, client.generation.sessions.open_socket, id, max_message_bytes=8, **socket_options)
        for bad in ["世" * 3, b"x" * 9, {"not": "encoded"}]:
            with pytest.raises((TypeError, ValueError)):
                await invoke(asynchronous, stream.send, bad)
        with pytest.raises(RuntimeError, match="application failure") as caught:
            if asynchronous:
                async with stream:
                    raise RuntimeError("application failure")
            else:
                with stream:
                    raise RuntimeError("application failure")
        assert isinstance(caught.value.cleanup_error, GenerationSocketCleanupError)
        assert state["messages"] == [] and state["close"] == 1
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_invalid_options_before_capability_and_origin_opt_in(socket_server, asynchronous):
    id, state, options, socket_options = socket_server
    client = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        for bad in [{"max_queue": None}, {"max_queue": 17}, {"max_message_bytes": True},
                    {"open_timeout": float("inf")}, {"close_timeout": 0},
                    {"max_duration_seconds": float("nan")}, {"max_duration_seconds": 3601},
                    {"relay_origin": "ws://example.com"}, {"relay_origin": "wss://example.com/path"}]:
            with pytest.raises(ValueError):
                await invoke(asynchronous, client.generation.sessions.open_socket, id, **{**socket_options, **bad})
        assert state["connect"] == 0
        with pytest.raises(APIResponseValidationError):
            await invoke(asynchronous, client.generation.sessions.open_socket, id)
        assert state["handshakes"] == []  # Different port is a different origin.
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("deadline", [False, True])
async def test_iteration_and_finite_lifetime_request_http_close(socket_server, asynchronous, deadline):
    id, state, options, socket_options = socket_server
    state["mode"] = "echo" if deadline else "finish"
    client = (AsyncQCloud if asynchronous else QCloud)(**options)
    try:
        stream = await invoke(asynchronous, client.generation.sessions.open_socket, id,
                              max_duration_seconds=0.1 if deadline else 10, **socket_options)
        if not deadline:
            await invoke(asynchronous, stream.send, "one message")
        messages = [message async for message in stream] if asynchronous else list(stream)
        assert messages == ([] if deadline else ["one message"])
        await invoke(asynchronous, stream.close)
        assert state["connect"] == state["close"] == 1
        assert stream.close_result.close_requested is True
    finally:
        await invoke(asynchronous, client.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("action", ["send", "close"])
async def test_nonreading_peer_cannot_hold_send_or_local_close(socket_server, asynchronous, action):
    id, state, options, _ = socket_server
    release = threading.Event()
    class NonReadingPeer(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            self.request.settimeout(3)
            request = b""
            while b"\r\n\r\n" not in request:
                request += self.request.recv(4096)
                assert len(request) <= 16384
            key = next(line.split(b":", 1)[1].strip() for line in request.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key:"))
            accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\nSec-WebSocket-Protocol: qcloud.realtime.v1\r\n\r\n")
            # Deliberately never read frames or answer close. No mocked client methods.
            release.wait(8)
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
    with Server(("127.0.0.1", 0), NonReadingPeer) as peer:
        thread = threading.Thread(target=peer.serve_forever, daemon=True)
        thread.start()
        origin = f"ws://127.0.0.1:{peer.server_address[1]}"
        state["override"] = {"websocket_url": origin + f"/v1/generation/sessions/{id}/socket"}
        client = (AsyncQCloud if asynchronous else QCloud)(**options)
        try:
            stream = await invoke(asynchronous, client.generation.sessions.open_socket, id,
                                  relay_origin=origin, send_timeout=0.1, close_timeout=0.1)
            started = time.monotonic()
            with pytest.raises((GenerationSocketError, GenerationSocketCleanupError)):
                if action == "send":
                    await invoke(asynchronous, stream.send, b"x" * (16 * 1024 * 1024))
                else:
                    await invoke(asynchronous, stream.close)
            assert time.monotonic() - started < 3
            assert state["connect"] == state["close"] == 1
            if asynchronous:
                assert stream._socket.transport.is_closing()
            else:
                assert stream._socket.socket.fileno() == -1
                assert not stream._socket.recv_events_thread.is_alive()
        finally:
            release.set()
            await invoke(asynchronous, client.close)
            peer.shutdown()
            thread.join(timeout=3)
