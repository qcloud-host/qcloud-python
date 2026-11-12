"""Request controls stay on the transport; malformed responses use SDK errors."""

import json
import traceback

import httpx
import pytest

from qcloud_ai import APIResponseValidationError, AsyncQCloud, QCloud, RateLimitError


CASES = [
    (
        "chat.completions.create",
        {"model": "test", "messages": []},
        {"choices": "invalid"},
    ),
    (
        "completions.create",
        {"model": "test", "prompt": "Hello"},
        {"choices": "invalid"},
    ),
    ("embeddings.create", {"model": "test", "input": "Hello"}, {"data": "invalid"}),
    (
        "messages.create",
        {"model": "test", "messages": [], "max_tokens": 8},
        {"content": "invalid"},
    ),
    ("models.list", {}, {"data": "invalid"}),
    ("models.retrieve", {"model": "test"}, {"capabilities": "invalid"}),
]


def method(client, path):
    for part in path.split("."):
        client = getattr(client, part)
    return client


@pytest.mark.parametrize("path,params,invalid", CASES)
def test_request_controls_are_not_sent_as_json(path, params, invalid):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.extensions["timeout"]["read"] == 7
        if request.content:
            assert "timeout" not in json.loads(request.content)
            assert "max_retries" not in json.loads(request.content)
        return httpx.Response(429, json={"error": {"message": "Slow down"}})

    with QCloud(
        api_key="fixture",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(RateLimitError):
            method(client, path)(**params, timeout=7, max_retries=0)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path,params,invalid", CASES)
async def test_async_request_controls_are_not_sent_as_json(path, params, invalid):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.extensions["timeout"]["read"] == 7
        if request.content:
            assert "timeout" not in json.loads(request.content)
            assert "max_retries" not in json.loads(request.content)
        return httpx.Response(429, json={"error": {"message": "Slow down"}})

    async with AsyncQCloud(
        api_key="fixture",
        max_retries=2,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(RateLimitError):
            await method(client, path)(**params, timeout=7, max_retries=0)
    assert len(requests) == 1


@pytest.mark.parametrize("path,params,invalid", CASES)
@pytest.mark.parametrize("shape", ["wrong_fields", "array", "null", "invalid_json"])
def test_malformed_response_is_typed_and_identified(path, params, invalid, shape):
    body = {"wrong_fields": invalid, "array": [], "null": None, "invalid_json": None}[
        shape
    ]
    response = httpx.Response(
        200,
        content=b"not json" if shape == "invalid_json" else json.dumps(body).encode(),
        headers={"x-request-id": "req-sync"},
    )
    with QCloud(
        api_key="fixture",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: response)
        ),
    ) as client:
        with pytest.raises(APIResponseValidationError) as caught:
            method(client, path)(**params)
    assert caught.value.request_id == "req-sync"
    assert caught.value.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("path,params,invalid", CASES)
@pytest.mark.parametrize("shape", ["wrong_fields", "array", "null", "invalid_json"])
async def test_async_malformed_response_is_typed_and_identified(
    path, params, invalid, shape
):
    body = {"wrong_fields": invalid, "array": [], "null": None, "invalid_json": None}[
        shape
    ]
    response = httpx.Response(
        200,
        content=b"not json" if shape == "invalid_json" else json.dumps(body).encode(),
        headers={"request-id": "req-async"},
    )
    async with AsyncQCloud(
        api_key="fixture",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: response)
        ),
    ) as client:
        with pytest.raises(APIResponseValidationError) as caught:
            await method(client, path)(**params)
    assert caught.value.request_id == "req-async"
    assert caught.value.status_code == 200


@pytest.mark.parametrize("path,params,invalid", CASES)
def test_invalid_controls_fail_before_dispatch(path, params, invalid):
    with QCloud(
        api_key="fixture",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("invalid controls reached the network")
            )
        ),
    ) as client:
        for options in ({"timeout": 0}, {"max_retries": -1}):
            with pytest.raises(ValueError):
                method(client, path)(**params, **options)


def test_schema_error_traceback_does_not_expose_response_values():
    private = "private-prompt-sample-do-not-log"
    with QCloud(api_key="fixture", http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": private})
    ))) as client:
        with pytest.raises(APIResponseValidationError) as caught:
            client.chat.completions.create(model="test", messages=[])
    assert private not in str(caught.value)
    assert private not in "".join(traceback.format_exception(caught.value))
