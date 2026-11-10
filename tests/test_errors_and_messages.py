import json
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from qcloud_ai import (
    QCloud,
    AsyncQCloud,
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    BadRequestError,
    ConflictError,
    InsufficientCreditsError,
    Message,
    MessageStreamEvent,
    RateLimitError,
    RateLimitInfo,
    UnprocessableEntityError,
)

PARAMS = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
REPLY = {"id": "chat-test", "choices": [{"message": {"role": "assistant", "content": "Hello"}}]}
MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "test-model",
    "content": [{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 3, "output_tokens": 2},
}


def make(handler, **opts):
    return QCloud(
        api_key="qc-test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=opts.pop("max_retries", 0),
        **opts,
    )


def sse(*events):
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream", "x-request-id": "req-s"})


def test_rate_limit_error_exposes_request_id_retry_after_and_limits():
    headers = {
        "x-request-id": "req-429",
        "retry-after": "7",
        "x-ratelimit-limit-requests": "60",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-limit-tokens": "100000",
        "x-ratelimit-remaining-tokens": "12",
    }
    body = {"error": {"type": "rate_limit_error", "code": "rate_limit_exceeded", "message": "Slow down"}}
    with make(lambda r: httpx.Response(429, json=body, headers=headers)) as c:
        with pytest.raises(RateLimitError) as caught:
            c.chat.completions.create(**PARAMS)
    error = caught.value
    assert error.status_code == 429 and error.message == "Slow down"
    assert error.request_id == "req-429" and error.code == "rate_limit_exceeded"
    assert error.retry_after == 7.0
    assert error.rate_limit == RateLimitInfo(60, 0, 100000, 12)
    assert error.headers["x-ratelimit-remaining-tokens"] == "12"


def test_http_date_retry_after_and_missing_limits():
    when = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    with make(lambda r: httpx.Response(402, json={"error": {"message": "Top up"}}, headers={"retry-after": when})) as c:
        with pytest.raises(InsufficientCreditsError) as caught:
            c.chat.completions.create(**PARAMS)
    assert 0 < caught.value.retry_after <= 30
    assert caught.value.rate_limit is None and caught.value.request_id is None
    assert caught.value.error_type == "billing_error"


@pytest.mark.parametrize(
    "status,cls,server_type",
    [(400, BadRequestError, "invalid_request_error"), (409, ConflictError, "schema_unavailable"), (422, UnprocessableEntityError, None)],
)
def test_status_classes_preserve_server_type_and_code(status, cls, server_type):
    error_body = {"message": "nope", "code": "capability_rejected"}
    if server_type:
        error_body["type"] = server_type
    with make(lambda r: httpx.Response(status, json={"error": error_body})) as c:
        with pytest.raises(cls) as caught:
            c.chat.completions.create(**PARAMS)
    assert isinstance(caught.value, APIError)
    assert caught.value.code == "capability_rejected"
    if server_type:
        assert caught.value.error_type == server_type


def test_anthropic_request_id_header_fallback():
    body = {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}, "request_id": "r-1"}
    with make(lambda r: httpx.Response(401, json=body, headers={"request-id": "r-1"})) as c:
        with pytest.raises(APIError) as caught:
            c.messages.create(model="m", max_tokens=8, messages=[{"role": "user", "content": "x"}])
    assert caught.value.request_id == "r-1" and caught.value.error_type == "authentication_error"


def test_post_connect_failure_is_retried_because_nothing_was_sent(monkeypatch):
    monkeypatch.setattr("qcloud_ai._base_client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=REPLY)

    with make(handler, max_retries=1) as c:
        assert c.chat.completions.create(**PARAMS).id == "chat-test"
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("slow"), httpx.WriteError("reset"), httpx.RemoteProtocolError("closed")])
def test_post_failures_after_send_are_not_replayed(failure, monkeypatch):
    monkeypatch.setattr("qcloud_ai._base_client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        raise failure

    with make(handler, max_retries=3) as c:
        with pytest.raises(APITimeoutError if isinstance(failure, httpx.TimeoutException) else APIConnectionError):
            c.chat.completions.create(**PARAMS)
    assert len(calls) == 1


def test_connect_failures_exhaust_retries(monkeypatch):
    monkeypatch.setattr("qcloud_ai._base_client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectTimeout("no route")

    with make(handler, max_retries=2) as c:
        with pytest.raises(APITimeoutError):
            c.chat.completions.create(**PARAMS)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_async_connect_retry_and_rate_limit_details(monkeypatch):
    async def pause(_):
        return None

    monkeypatch.setattr("qcloud_ai._base_client.asyncio.sleep", pause)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(429, json={"error": {"message": "busy"}}, headers={"retry-after": "2", "x-ratelimit-remaining-requests": "0"})

    async with AsyncQCloud(api_key="qc-test", max_retries=1, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as c:
        with pytest.raises(RateLimitError) as caught:
            await c.chat.completions.create(**PARAMS)
    assert len(calls) == 2
    assert caught.value.retry_after == 2.0 and caught.value.rate_limit.remaining_requests == 0


def test_messages_create_sends_version_and_parses_message():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=MESSAGE)

    with make(handler) as c:
        message = c.messages.create(model="test-model", max_tokens=16, messages=[{"role": "user", "content": "hi"}], system="Be brief")
    assert isinstance(message, Message) and message.text == "Hello" and message.usage.output_tokens == 2
    request = seen[0]
    assert request.url.path.endswith("/v1/messages")
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert request.headers["authorization"] == "Bearer qc-test"
    assert json.loads(request.content) == {"model": "test-model", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}], "system": "Be brief"}


def test_messages_stream_ends_on_message_stop():
    events = [
        {"type": "message_start", "message": {**MESSAGE, "content": [], "usage": {"input_tokens": 0, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "γειά 🌍"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"input_tokens": 3, "output_tokens": 2}},
        {"type": "message_stop"},
    ]
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return sse(*events)

    with make(handler) as c:
        with c.messages.create(model="m", max_tokens=8, messages=[{"role": "user", "content": "x"}], stream=True) as stream:
            received = list(stream)
    assert seen[0]["stream"] is True
    assert all(isinstance(e, MessageStreamEvent) for e in received)
    assert [e.type for e in received][-1] == "message_stop"
    assert "".join(e.delta["text"] for e in received if e.type == "content_block_delta") == "γειά 🌍"
    assert received[4].usage == {"input_tokens": 3, "output_tokens": 2}


def test_messages_stream_truncation_and_error_event():
    with make(lambda r: sse({"type": "message_start", "message": MESSAGE})) as c:
        with pytest.raises(APIResponseValidationError, match="terminal event"):
            list(c.messages.create(model="m", max_tokens=8, messages=[], stream=True))
    error_event = {"type": "error", "error": {"type": "overloaded_error", "message": "Provider overloaded"}}
    with make(lambda r: sse({"type": "message_start", "message": MESSAGE}, error_event)) as c:
        with pytest.raises(APIError) as caught:
            list(c.messages.create(model="m", max_tokens=8, messages=[], stream=True))
    assert caught.value.error_type == "overloaded_error" and caught.value.request_id == "req-s"


@pytest.mark.asyncio
async def test_async_messages_stream():
    events = [{"type": "message_start", "message": MESSAGE}, {"type": "message_stop"}]
    async with AsyncQCloud(api_key="qc-test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: sse(*events)))) as c:
        stream = await c.messages.create(model="m", max_tokens=8, messages=[], stream=True)
        received = [event async for event in stream]
        message = None
    assert [e.type for e in received] == ["message_start", "message_stop"]
    async with AsyncQCloud(api_key="qc-test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=MESSAGE)))) as c:
        message = await c.messages.create(model="m", max_tokens=8, messages=[])
    assert message.text == "Hello"
