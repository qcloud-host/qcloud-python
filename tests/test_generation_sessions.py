from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

from qcloud_ai import (
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    AsyncQCloud,
    QCloud,
)


@pytest.fixture
def session_server():
    id = str(uuid4())
    state = {
        "posts": 0,
        "offers": 0,
        "closed": 0,
        "failure": 0,
        "mode": "complete",
        "transport": "websocket",
        "capability": None,
        "bodies": [],
        "tokens": [],
        "paths": [],
    }

    def session(status="created"):
        return {
            "object": "generation.session",
            "id": id,
            "model": "qcloud/session",
            "transport": state["transport"],
            "status": status,
            "created_at": "2026-11-06T00:00:00Z",
            "updated_at": "2026-11-06T00:00:00Z",
            "connected_at": None,
            "completed_at": None,
            "deadline_at": None,
            "expires_at": "2026-11-06T00:05:00Z",
            "max_duration_seconds": 300,
            "close_requested": status == "closed",
            "error": None,
            "license": None,
            "billing": {
                "mode": "metered",
                "status": "pending",
                "currency": "USD",
                "markup_multiplier": 2,
                "cost_usd": None,
            },
        }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_json(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            state["paths"].append(self.path)
            self.send_json({"data": session()})

        def do_POST(self):
            state["paths"].append(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if body:
                state["bodies"].append(json.loads(body))
            if self.path == "/v1/generation/sessions":
                state["posts"] += 1
                if state["failure"]:
                    return self.send_json(
                        {
                            "error": {
                                "message": "Fixture unavailable",
                                "type": "unavailable",
                            }
                        },
                        state["failure"],
                    )
                state["transport"] = json.loads(body)["transport"]
                return self.send_json({"data": session()}, 201)
            if self.path.endswith("/connect"):
                if state["capability"] is not None:
                    return self.send_json({"data": state["capability"]}, 201)
                common = {
                    "transport": state["transport"],
                    "session_id": id,
                    "token": "single-use",
                    "expires_at": "2026-11-06T00:00:30Z",
                }
                if state["transport"] == "websocket":
                    common.update(
                        websocket_url="wss://qcloud.example.test/realtime",
                        subprotocols=["qcloud.realtime.v1", "qcloud.cap.single-use"],
                        encoding="msgpack",
                    )
                else:
                    common["url"] = "https://qcloud.example.test/offer"
                return self.send_json({"data": common}, 201)
            if self.path.endswith("/close"):
                return self.send_json({"data": session("closed")}, 202)
            if self.path.endswith("/offer"):
                state["offers"] += 1
                state["tokens"].append(self.headers["X-QCloud-Session-Token"])
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("X-Request-Id", "session-fixture")
                self.end_headers()
                try:
                    if state["mode"] == "stall":
                        time.sleep(0.3)
                        return
                    if state["mode"] == "error":
                        self.wfile.write(
                            b'event: error\ndata: {"error":{"code":"session_failed","message":"Session failed"}}\n\n'
                        )
                        return
                    answer = (
                        "event: answer\r\ndata: "
                        + json.dumps(
                            {
                                "session_id": str(uuid4())
                                if state["mode"] == "mismatch"
                                else id,
                                "type": "answer",
                                "sdp": "v=0\r\ns=🌍",
                            },
                            ensure_ascii=False,
                        )
                        + "\r\n\r\n"
                    ).encode()
                    for offset in range(0, len(answer), 3):
                        self.wfile.write(answer[offset : offset + 3])
                    if state["mode"] == "hold":
                        for _ in range(100):
                            self.wfile.write(b": keepalive\n\n")
                            time.sleep(0.01)
                        return
                    if state["mode"] == "duplicate":
                        self.wfile.write(answer)
                    if state["mode"] == "complete":
                        self.wfile.write(
                            (
                                "event: closed\ndata: "
                                + json.dumps(
                                    {"session_id": id, "reason": "session_finished"}
                                )
                                + "\n\n"
                            ).encode()
                        )
                    if state["mode"] == "truncated_closed":
                        self.wfile.write(
                            (
                                "event: closed\ndata: "
                                + json.dumps(
                                    {"session_id": id, "reason": "session_finished"}
                                )
                            ).encode()
                        )
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    state["closed"] += 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield (
        id,
        state,
        {
            "api_key": "qc-fixture",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "max_retries": 3,
        },
    )
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_session_control_and_no_automatic_paid_retry(session_server):
    id, state, options = session_server
    with QCloud(**options) as client:
        for transport in ["websocket", "webrtc"]:
            request_id = str(uuid4())
            assert (
                client.generation.sessions.create(
                    model="qcloud/session",
                    transport=transport,
                    billing_mode="metered",
                    client_request_id=request_id,
                ).id
                == id
            )
            assert state["bodies"][-1]["client_request_id"] == request_id
            assert client.generation.sessions.retrieve(id).transport == transport
            capability = client.generation.sessions.connect(id)
            assert (
                capability.transport == transport and capability.token == "single-use"
            )
            assert "single-use" not in repr(capability)
            assert client.generation.sessions.close(id).status == "closed"
        state["failure"] = 429
        before = state["posts"]
        with pytest.raises(APIError) as error:
            client.generation.sessions.create(
                model="qcloud/session",
                transport="websocket",
                billing_mode="metered",
                client_request_id=request_id,
            )
        assert error.value.client_request_id == request_id
        assert state["posts"] == before + 1


@pytest.mark.asyncio
async def test_capability_signaling_variants_and_unknown_protocols(session_server):
    id, state, options = session_server
    rtc = {
        "transport": "webrtc",
        "signaling": "websocket",
        "protocol": "rtc-signaling-v1",
        "session_id": id,
        "websocket_url": "wss://qcloud.example.test/realtime",
        "token": "single-use",
        "expires_at": "2026-11-06T00:00:30Z",
        "subprotocols": ["qcloud.realtime.v1", "qcloud.cap.single-use"],
        "encoding": "msgpack",
    }
    with QCloud(**options) as client:
        state["capability"] = rtc
        capability = client.generation.sessions.connect(id)
        assert capability.transport == "webrtc" and capability.signaling == "websocket"
        assert (
            capability.protocol == "rtc-signaling-v1"
            and capability.encoding == "msgpack"
        )
        assert capability.websocket_url == rtc["websocket_url"]
        assert "single-use" not in repr(capability)
        for override in [
            {"protocol": "unknown"},
            {"protocol": None},
            {"encoding": "json"},
            {"signaling": "unknown"},
            {"transport": "unknown"},
            {"websocket_url": ""},
            {"subprotocols": []},
            {"session_id": str(uuid4())},
        ]:
            state["capability"] = {**rtc, **override}
            with pytest.raises(APIResponseValidationError):
                client.generation.sessions.connect(id)
        state["capability"] = {
            "transport": "webrtc",
            "signaling": "sse",
            "session_id": id,
            "url": "https://qcloud.example.test/offer",
            "token": "single-use",
            "expires_at": rtc["expires_at"],
        }
        assert client.generation.sessions.connect(id).signaling == "sse"
        state["capability"] = {**rtc, "transport": "websocket"}
        assert client.generation.sessions.connect(id).transport == "websocket"
    state["capability"] = rtc
    async with AsyncQCloud(**options) as client:
        capability = await client.generation.sessions.connect(id)
        assert (
            capability.signaling == "websocket"
            and capability.protocol == "rtc-signaling-v1"
        )
        assert "single-use" not in repr(capability)
    assert state["offers"] == 0


def test_session_offer_stream_and_explicit_cleanup(session_server):
    id, state, options = session_server
    with QCloud(**options) as client:
        with client.generation.sessions.offer(
            id, sdp="offer", session_token="single-use"
        ) as stream:
            events = list(stream)
        assert [event.event for event in events] == ["answer", "closed"]
        assert events[0].data["sdp"] == "v=0\r\ns=🌍"
        assert state["tokens"] == ["single-use"] and all(
            "single-use" not in path for path in state["paths"]
        )
        state["mode"] = "hold"
        before = state["closed"]
        with client.generation.sessions.offer(
            id, sdp="offer", session_token="single-use"
        ) as stream:
            assert next(stream).event == "answer"
        for _ in range(20):
            if state["closed"] > before:
                break
            time.sleep(0.01)
        assert state["closed"] == before + 1


@pytest.mark.parametrize(
    "mode", ["error", "duplicate", "mismatch", "truncated", "truncated_closed"]
)
def test_session_stream_failures_do_not_succeed_silently(session_server, mode):
    id, state, options = session_server
    state["mode"] = mode
    with QCloud(**options) as client:
        with pytest.raises(
            APIError if mode == "error" else APIResponseValidationError
        ) as error:
            with client.generation.sessions.offer(
                id, sdp="offer", session_token="single-use"
            ) as stream:
                list(stream)
        if mode == "error":
            assert error.value.request_id == "session-fixture"
        assert state["offers"] == 1


@pytest.mark.asyncio
async def test_async_session_control_offer_and_cancellation(session_server):
    id, state, options = session_server
    async with AsyncQCloud(**options) as client:
        assert (
            await client.generation.sessions.create(
                model="qcloud/session", transport="webrtc", billing_mode="metered"
            )
        ).id == id
        assert (await client.generation.sessions.connect(id)).transport == "webrtc"
        async with await client.generation.sessions.offer(
            id, sdp="offer", session_token="single-use"
        ) as stream:
            events = [event async for event in stream]
        assert [event.event for event in events] == ["answer", "closed"]
        assert (await client.generation.sessions.retrieve(id)).id == id
        assert (await client.generation.sessions.close(id)).status == "closed"
        state["mode"] = "stall"
        async with await client.generation.sessions.offer(
            id, sdp="offer", session_token="single-use", timeout=0.03
        ) as stream:
            with pytest.raises(APITimeoutError):
                await anext(stream)
        async with await client.generation.sessions.offer(
            id, sdp="offer", session_token="single-use"
        ) as stream:
            pending = asyncio.create_task(anext(stream))
            await asyncio.sleep(0.01)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending


def test_session_invalid_inputs_fail_before_network(session_server):
    id, state, options = session_server
    with QCloud(**options) as client:
        with pytest.raises(ValueError):
            client.generation.sessions.create(
                model="qcloud/session",
                transport="websocket",
                billing_mode="metered",
                max_duration_seconds=0,
            )
        with pytest.raises(ValueError):
            client.generation.sessions.offer(
                id, sdp="offer", session_token="bad\r\ntoken"
            )
        with pytest.raises(ValueError):
            client.generation.sessions.retrieve("not-uuid")
        assert state["posts"] == state["offers"] == 0
