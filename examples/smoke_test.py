"""Runs the examples against a local fake QCloud API (no network, no billing).

    python -m pip install -e ".[dev]" fastapi django   # framework checks are skipped if absent
    python examples/smoke_test.py

The fake implements only the wire shapes the examples use. It proves the
examples run and handle errors as documented; it is not a backend contract.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEXT = "γειά 🌍"
USAGE = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
calls: list[dict] = []
mode = {"chat": "ok"}


class FakeQCloud(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _json(self, status, body, headers=None):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("x-request-id", f"req-{len(calls)}")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, events, named=False):
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("x-request-id", f"req-{len(calls)}")
        self.end_headers()
        for event in events:
            prefix = f"event: {event['type']}\n" if named else ""
            self.wfile.write(f"{prefix}data: {json.dumps(event)}\n\n".encode())
        if not named:
            self.wfile.write(b"data: [DONE]\n\n")

    def do_GET(self):
        calls.append({"path": self.path})
        if self.path.endswith("/models"):
            self._json(200, {"object": "list", "data": [{"id": "fake/chat", "object": "model"}]})
        else:
            self._json(404, {"error": {"message": "Not found", "type": "invalid_request_error"}})

    def do_POST(self):
        assert self.headers["authorization"] == "Bearer qc-smoke"
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        calls.append({"path": self.path, "body": body})
        if self.path.endswith("/chat/completions"):
            prompt = body["messages"][0]["content"]
            if prompt == "rate-limit" or mode["chat"] == "rate-limit":
                mode["chat"] = "ok"
                return self._json(429, {"error": {"type": "rate_limit_error", "code": "rate_limit_exceeded", "message": "Slow down"}},
                                  {"retry-after": "0", "x-ratelimit-remaining-requests": "0"})
            if prompt == "no-credits":
                return self._json(402, {"error": {"type": "billing_error", "message": "Insufficient credits"}})
            if prompt == "bad":
                return self._json(400, {"error": {"type": "invalid_request_error", "code": "unsupported_option", "message": "Request contains unsupported options"}})
            if body.get("stream"):
                common = {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": body["model"]}
                return self._sse([{**common, "choices": [{"index": 0, "delta": {"content": TEXT}, "finish_reason": "stop"}]},
                                  {**common, "choices": [], "usage": USAGE}])
            return self._json(200, {"id": "c", "object": "chat.completion", "created": 1, "model": body["model"],
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": TEXT}, "finish_reason": "stop"}],
                                    "usage": USAGE})
        if self.path.endswith("/messages"):
            assert self.headers["anthropic-version"] == "2023-06-01"
            message = {"id": "m", "type": "message", "role": "assistant", "model": body["model"],
                       "content": [{"type": "text", "text": TEXT}], "stop_reason": "end_turn",
                       "stop_sequence": None, "usage": {"input_tokens": 7, "output_tokens": 3}}
            if body.get("stream"):
                return self._sse([
                    {"type": "message_start", "message": {**message, "content": [], "usage": {"input_tokens": 0, "output_tokens": 0}}},
                    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": TEXT}},
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"input_tokens": 7, "output_tokens": 3}},
                    {"type": "message_stop"},
                ], named=True)
            return self._json(200, message)
        self._json(404, {"error": {"message": "Not found"}})


def sse_text(raw: str) -> str:
    """Concatenate the ``text`` fields of an example's SSE response."""
    parts = []
    for line in raw.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            parts.append(json.loads(line[6:]).get("text", ""))
    assert raw.rstrip().endswith("data: [DONE]"), raw
    return "".join(parts)


def run_script(name: str) -> str:
    result = subprocess.run([sys.executable, str(HERE / name)], capture_output=True, text=True, timeout=60, env=os.environ.copy())
    assert result.returncode == 0, f"{name} failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout


def check_fastapi() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("skip fastapi (not installed)")
        return
    sys.path.insert(0, str(HERE))
    module = importlib.import_module("fastapi_app")
    with TestClient(module.app) as http:
        reply = http.post("/chat", json={"message": "hi"})
        assert reply.status_code == 200 and reply.json()["reply"] == TEXT, reply.text
        assert reply.json()["usage"]["total_tokens"] == 10
        stream = http.post("/chat/stream", json={"message": "hi"})
        assert stream.status_code == 200 and sse_text(stream.text) == TEXT, stream.text
        limited = http.post("/chat", json={"message": "rate-limit"})
        assert limited.status_code == 429 and limited.headers["retry-after"] == "0", limited.text
        assert limited.headers["x-qcloud-request-id"].startswith("req-")
        assert http.post("/chat", json={"message": "no-credits"}).status_code == 402
        bad = http.post("/chat", json={"message": "bad"})
        assert bad.status_code == 400 and bad.json()["code"] == "unsupported_option"
    print("fastapi ok")


def check_django() -> None:
    try:
        import django
        from django.conf import settings
    except ImportError:
        print("skip django (not installed)")
        return
    settings.configure(DEBUG=False, SECRET_KEY="smoke", ROOT_URLCONF=__name__, ALLOWED_HOSTS=["testserver"],
                       INSTALLED_APPS=[], MIDDLEWARE=[])
    django.setup()
    from django.test import Client
    from django.urls import path

    sys.path.insert(0, str(HERE))
    views = importlib.import_module("django_views")
    globals()["urlpatterns"] = [path("chat/", views.chat), path("chat/stream/", views.chat_stream)]
    http = Client()
    reply = http.post("/chat/", data=json.dumps({"message": "hi"}), content_type="application/json")
    assert reply.status_code == 200 and reply.json()["reply"] == TEXT, reply.content
    stream = http.post("/chat/stream/", data=json.dumps({"message": "hi"}), content_type="application/json")
    assert stream.status_code == 200 and sse_text(b"".join(stream.streaming_content).decode()) == TEXT
    limited = http.post("/chat/", data=json.dumps({"message": "rate-limit"}), content_type="application/json")
    assert limited.status_code == 429 and limited["Retry-After"] == "0"
    print("django ok")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeQCloud)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ.update(QCLOUD_API_KEY="qc-smoke", QCLOUD_MODEL="fake/chat",
                      QCLOUD_BASE_URL=f"http://127.0.0.1:{server.server_address[1]}/v1")
    try:
        assert TEXT in run_script("quickstart.py")
        assert TEXT in run_script("async_stream.py")
        output = run_script("messages.py")
        assert output.count(TEXT) == 2 and "output_tokens" in output, output
        mode["chat"] = "rate-limit"  # the worker's first request is rejected with 429, then re-enqueued
        output = run_script("background_worker.py")
        assert output.count(" done ") == 2, output
        print("scripts ok")
        check_fastapi()
        check_django()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
