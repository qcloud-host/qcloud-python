from __future__ import annotations

import asyncio

import httpx
import pytest

from qcloud_ai import (QCloud, AsyncQCloud, APIError, APIResponseValidationError,
                       APITimeoutError, AuthenticationError, PermissionDeniedError, NotFoundError)

ID = "abcdef12-3456-4789-abcd-ef1234567890"
RECEIPT = dict(id=ID, object="generation.file", url=f"qcloud://files/{ID}", filename="εικόνα.png",
               content_type="image/png", size_bytes=123, sha256="a" * 64,
               created_at="2026-11-08T10:00:00+00:00", expires_at="2026-11-15T10:00:00Z")


async def invoke(method, asynchronous, *args, **kwargs):
    value = method(*args, **kwargs)
    return await value if asynchronous else value


def client(asynchronous, handler):
    transport = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=httpx.MockTransport(handler), follow_redirects=True)
    return (AsyncQCloud if asynchronous else QCloud)(api_key="qc-fixture", organization=ID,
               base_url="https://qcloud.example/api/v1", http_client=transport, max_retries=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_metadata_identity_origin_and_organization(asynchronous):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and str(request.url) == f"https://qcloud.example/api/v1/generation/files/{ID}"
        assert request.headers["Authorization"] == "Bearer qc-fixture" and request.headers["X-QCloud-Organization"] == ID
        assert request.extensions["timeout"]["read"] == 12
        return httpx.Response(200, json={"data": RECEIPT})

    sdk = client(asynchronous, handler)
    try:
        result = await invoke(sdk.generation.files.retrieve, asynchronous, ID.upper(), timeout=12)
        assert result.model_dump() == RECEIPT
        for invalid in ("https://foreign.example/file", f"qcloud://files/{ID}", "../file", ID + "\n", ID.replace("-", "")):
            with pytest.raises(ValueError, match="UUID"):
                await invoke(sdk.generation.files.retrieve, asynchronous, invalid)
        assert len(requests) == 1
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_metadata_rejects_wrong_identity_urls_and_malformed_fields(asynchronous):
    data = None
    sdk = client(asynchronous, lambda _: httpx.Response(200, json=data))
    invalid = [dict(id="fedcba98-7654-4321-abcd-0123456789ab"), dict(id=ID.upper()), dict(object="file"),
               dict(url="https://foreign.example/file"), dict(url=f"qcloud://files/{ID}?key=secret"),
               dict(filename="../file"), dict(filename="\u0085file"), dict(filename="é" * 128), dict(filename=" "),
               dict(content_type="image/png\n"), dict(content_type="Image/PNG"), dict(content_type="image/png; charset=utf8"),
               dict(size_bytes=0), dict(size_bytes=True), dict(size_bytes=268435457), dict(size_bytes=1.5),
               dict(sha256="A" * 64), dict(sha256="a" * 64 + "\n"), dict(created_at="not a date"),
               dict(created_at="2026-11-08T10:00:00"), dict(expires_at=RECEIPT["created_at"])]
    try:
        for patch in invalid:
            data = {"data": {**RECEIPT, **patch}}
            with pytest.raises(APIResponseValidationError):
                await invoke(sdk.generation.files.retrieve, asynchronous, ID)
        for malformed in (None, [], {}, {"data": None}, {"data": []}):
            data = malformed
            with pytest.raises(APIResponseValidationError):
                await invoke(sdk.generation.files.retrieve, asynchronous, ID)
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_metadata_typed_errors_and_no_redirect_forwarding(asynchronous):
    status, requests = 401, []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"code": "input_file_unavailable", "message": "File unavailable"}},
                              headers={"X-Request-Id": "metadata-request", "Location": "https://foreign.example/file"})

    sdk = client(asynchronous, handler)
    try:
        for status, expected in ((401, AuthenticationError), (403, PermissionDeniedError), (404, NotFoundError), (410, APIError), (302, APIError)):
            before = len(requests)
            with pytest.raises(expected) as caught:
                await invoke(sdk.generation.files.retrieve, asynchronous, ID)
            assert caught.value.status_code == status and caught.value.request_id == "metadata-request"
            assert len(requests) == before + 1 and requests[-1].url.host == "qcloud.example"
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_metadata_timeout_remains_typed(asynchronous):
    def handler(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    sdk = client(asynchronous, handler)
    try:
        with pytest.raises(APITimeoutError):
            await invoke(sdk.generation.files.retrieve, asynchronous, ID, timeout=0.1)
    finally:
        await invoke(sdk.close, asynchronous)


@pytest.mark.asyncio
async def test_async_metadata_cancellation_closes_pending_transport():
    entered, closed = asyncio.Event(), asyncio.Event()

    async def handler(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    sdk = client(True, handler)
    try:
        pending = asyncio.create_task(sdk.generation.files.retrieve(ID))
        await asyncio.wait_for(entered.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert closed.is_set()
    finally:
        await sdk.close()
