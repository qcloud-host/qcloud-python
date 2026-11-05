import json
import httpx
import pytest
from qcloud_ai import (
    QCloudAI,
    AsyncQCloudAI,
    AuthenticationError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    APIConnectionError,
)
from qcloud_ai._streaming import Stream, AsyncStream
from qcloud_ai.types.chat import ChatCompletionChunk

PARAMS = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
REPLY = {
    "id": "chat-test",
    "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
}


def make(handler, **opts):
    return QCloudAI(
        api_key="qc-test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=opts.pop("max_retries", 0),
        **opts,
    )


def test_stream_http_error_has_request_id():
    with make(
        lambda r: httpx.Response(
            401,
            json={"error": {"message": "No access"}},
            headers={"x-request-id": "req-test"},
        )
    ) as c:
        with pytest.raises(AuthenticationError) as error:
            c.chat.completions.create(**PARAMS, stream=True)
        assert error.value.request_id == "req-test"


def test_retries_and_authentication(monkeypatch):
    waits = []
    monkeypatch.setattr("qcloud_ai._base_client.time.sleep", waits.append)
    calls = []

    def handler(r):
        calls.append(r)
        return (
            httpx.Response(429, json={"error": {}}, headers={"retry-after": "2"})
            if len(calls) == 1
            else httpx.Response(200, json=REPLY)
        )

    with make(handler, max_retries=1) as c:
        assert c.chat.completions.create(**PARAMS).id == "chat-test"
    assert len(calls) == 2 and waits == [2]
    calls.clear()

    def bad(r):
        calls.append(r)
        return httpx.Response(401, json={"error": {}})

    with make(bad, max_retries=3) as c:
        with pytest.raises(AuthenticationError):
            c.models.list()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,exception", [(502, APIError), (200, APIResponseValidationError)]
)
def test_html_responses(status, exception):
    with make(lambda r: httpx.Response(status, text="<html>bad</html>")) as c:
        with pytest.raises(exception):
            c.models.list()


def test_stream_content_type():
    with make(lambda r: httpx.Response(200, json=REPLY)) as c:
        with pytest.raises(APIResponseValidationError):
            c.chat.completions.create(**PARAMS, stream=True)


def test_transport_errors():
    for error, expected in [
        (httpx.ConnectError("down"), APIConnectionError),
        (httpx.ReadTimeout("late"), APITimeoutError),
    ]:

        def handler(r):
            raise error

        with make(handler) as c:
            with pytest.raises(expected):
                c.models.list()


def test_model_path_and_tool_parameters():
    requests = []

    def handler(r):
        requests.append(r)
        return httpx.Response(200, json=REPLY)

    with make(handler) as c:
        c.models.retrieve("org/model?x")
        assert str(requests[-1].url).endswith("/models/org%2Fmodel%3Fx")
        c.chat.completions.create(
            **PARAMS,
            tools=[{"type": "function", "function": {"name": "weather"}}],
            response_format={"type": "json_object"},
        )
        body = json.loads(requests[-1].content)
        assert body["tools"][0]["function"]["name"] == "weather"
        assert requests[-1].headers["authorization"] == "Bearer qc-test"


def test_sse_framing_done_and_cleanup():
    response = httpx.Response(
        200,
        content=': ping\r\ndata:{"choices":[],\r\ndata: "model":"γειά 🌍"}\r\n\r\ndata:[DONE]\r\n\r\ndata:bad\r\n\r\n'.encode(),
    )
    chunks = list(Stream(response, cast=ChatCompletionChunk))
    assert len(chunks) == 1 and chunks[0].model == "γειά 🌍"
    assert response.is_closed
    response = httpx.Response(200, content=b'data:{"model":"eof"}')
    assert list(Stream(response, cast=ChatCompletionChunk))[0].model == "eof"


@pytest.mark.parametrize(
    "payload,exception",
    [
        (b"not-json", APIResponseValidationError),
        (b'{"error":{"message":"upstream"}}', APIError),
    ],
)
def test_sse_errors(payload, exception):
    response = httpx.Response(200, content=b"data:" + payload + b"\n\n")
    with pytest.raises(exception):
        list(Stream(response, cast=ChatCompletionChunk))
    assert response.is_closed


@pytest.mark.asyncio
async def test_async_retry_error_and_stream(monkeypatch):
    waits = []

    async def pause(delay):
        waits.append(delay)

    monkeypatch.setattr("qcloud_ai._base_client.asyncio.sleep", pause)
    calls = []

    async def handler(r):
        calls.append(r)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {}}, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            content=b'data:{"model":"test"}\n\ndata:[DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    async with AsyncQCloudAI(
        api_key="qc-test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=1,
    ) as c:
        async with await c.chat.completions.create(**PARAMS, stream=True) as stream:
            chunks = [chunk async for chunk in stream]
        assert chunks[0].model == "test" and len(calls) == 2 and waits == [0]
    async with AsyncQCloudAI(
        api_key="qc-test",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(401, json={"error": {}})
            )
        ),
    ) as c:
        with pytest.raises(AuthenticationError):
            await c.chat.completions.create(**PARAMS, stream=True)


def test_invalid_configuration():
    for options in [
        {"max_retries": -1},
        {"timeout": 0},
        {"base_url": "https://secret@example.com/v1"},
    ]:
        with pytest.raises(ValueError):
            QCloudAI(api_key="qc-test", **options)
