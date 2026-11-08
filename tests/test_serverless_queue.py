from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from qcloud_ai import APIConnectionError, APIError, APIResponseValidationError, AsyncQCloud, QCloud

ORG, ID = str(uuid4()), str(uuid4())
PROFILE = dict(id="fixture-small", name="Small model", model="Example/Model", gpu_memory_gb=24, disk_gb=30, pricing=None,
               limits=dict(max_workers=1, idle_timeout_seconds=90, execution_timeout_seconds=600))
DRAFT = dict(id=ID, name="SDK draft", status="draft", profile_id=PROFILE["id"], profile_name=PROFILE["name"], model=PROFILE["model"],
             created_at="2026-11-09T00:00:00+00:00", updated_at="2026-11-09T00:00:00.123Z")
CATALOG = dict(stage="draft_preview", runtime_available=False, creation_available=True, profiles=[PROFILE], unsupported=["job-execution"])


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def mode(request):
    return request.param


def call(mode, value, operation, status=200):
    calls = []
    def handler(request):
        calls.append(request)
        if isinstance(value, Exception):
            raise value
        return httpx.Response(status, json=value)
    if mode:
        async def run():
            async with AsyncQCloud(api_key="qc-fixture", base_url="http://127.0.0.1:1/v1", organization=ORG, max_retries=3,
                                   http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
                return await operation(client)
        result = asyncio.run(run())
    else:
        with QCloud(api_key="qc-fixture", base_url="http://127.0.0.1:1/v1", organization=ORG, max_retries=3,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
            result = operation(client)
    return result, calls


def test_catalog_and_draft_only_public_projection(mode):
    value = {**CATALOG, "provider": "private", "profiles": [{**PROFILE, "image": "private", "gpu_pools": ["private"]}]}
    result, calls = call(mode, value, lambda c: c.serverless.queue.catalog(org_id=ORG.upper()))
    assert result.model_dump() == CATALOG
    assert str(calls[0].url) == f"http://127.0.0.1:1/v1/serverless/queue/catalog?org_id={ORG}"
    assert calls[0].headers["authorization"] == "Bearer qc-fixture"
    assert calls[0].headers["x-qcloud-organization"] == ORG
    empty, _ = call(mode, {**CATALOG, "creation_available": False, "profiles": []}, lambda c: c.serverless.queue.catalog())
    assert empty.profiles == [] and empty.runtime_available is False


def test_create_sends_stable_identity_and_projects_private_fields(mode):
    result, calls = call(mode, {"data": {**DRAFT, "native_endpoint_id": "private"}},
                         lambda c: c.serverless.queue.deployments.create(name="  SDK draft  ", profile_id=PROFILE["id"], org_id=ORG), 201)
    assert result.model_dump() == DRAFT
    body = json.loads(calls[0].content)
    assert body == dict(name=DRAFT["name"], profile_id=PROFILE["id"], org_id=ORG, client_request_id=body["client_request_id"])
    assert len(body["client_request_id"]) == 36
    assert len(calls) == 1 and calls[0].method == "POST"


@pytest.mark.parametrize("status", [409, 429, 503])
def test_post_errors_never_retry_and_keep_recovery_id(mode, status):
    request_id, calls = str(uuid4()), []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "fixture failure", "code": "request_conflict"}})
    async def async_run():
        async with AsyncQCloud(api_key="qc-fixture", max_retries=9, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as c:
            await c.serverless.queue.deployments.create(name=DRAFT["name"], profile_id=PROFILE["id"], client_request_id=request_id.upper())
    with pytest.raises(APIError) as raised:
        if mode:
            asyncio.run(async_run())
        else:
            with QCloud(api_key="qc-fixture", max_retries=9, http_client=httpx.Client(transport=httpx.MockTransport(handler))) as c:
                c.serverless.queue.deployments.create(name=DRAFT["name"], profile_id=PROFILE["id"], client_request_id=request_id.upper())
    assert raised.value.status_code == status and raised.value.client_request_id == request_id
    assert len(calls) == 1


def test_connection_error_preserves_generated_id(mode):
    with pytest.raises(APIConnectionError) as raised:
        call(mode, httpx.ConnectError("lost acknowledgement"), lambda c: c.serverless.queue.deployments.create(name=DRAFT["name"], profile_id=PROFILE["id"]))
    assert len(raised.value.client_request_id) == 36


def test_list_retrieve_and_identity_validation(mode):
    result, _ = call(mode, {"data": [{**DRAFT, "profile_snapshot": {}}]}, lambda c: c.serverless.queue.deployments.list())
    assert result.model_dump() == {"data": [DRAFT]}
    result, calls = call(mode, {"data": DRAFT}, lambda c: c.serverless.queue.deployments.retrieve(ID.upper(), org_id=ORG))
    assert result.model_dump() == DRAFT
    assert str(calls[0].url).endswith(f"/deployments/{ID}?org_id={ORG}")
    with pytest.raises(APIResponseValidationError):
        call(mode, {"data": DRAFT}, lambda c: c.serverless.queue.deployments.retrieve(str(uuid4())))
    for value in [None, {}, {"data": [DRAFT, DRAFT]}, {"data": [DRAFT] * 101}]:
        with pytest.raises(APIResponseValidationError):
            call(mode, value, lambda c: c.serverless.queue.deployments.list())


def test_invalid_input_rejected_without_transport(mode):
    for params in [dict(name="x", profile_id=PROFILE["id"]), dict(name="x\x01y", profile_id=PROFILE["id"]),
                   dict(name="😀" * 41, profile_id=PROFILE["id"]), dict(name=DRAFT["name"], profile_id="fixture-small\n"),
                   dict(name=DRAFT["name"], profile_id=PROFILE["id"], client_request_id="bad"),
                   dict(name=DRAFT["name"], profile_id=PROFILE["id"], org_id="bad")]:
        with pytest.raises(ValueError):
            call(mode, AssertionError("must not send"), lambda c: c.serverless.queue.deployments.create(**params))
    with pytest.raises(ValueError):
        call(mode, AssertionError("must not send"), lambda c: c.serverless.queue.deployments.retrieve("https://other.example/private"))


def test_malformed_responses_fail_closed(mode):
    request_id = str(uuid4())
    for value in [{**DRAFT, "status": "running"}, {**DRAFT, "id": "provider-id"}, {**DRAFT, "created_at": "today"}, {**DRAFT, "name": "Different draft"}]:
        with pytest.raises(APIResponseValidationError) as raised:
            call(mode, {"data": value}, lambda c: c.serverless.queue.deployments.create(name=DRAFT["name"], profile_id=PROFILE["id"], client_request_id=request_id))
        assert raised.value.client_request_id == request_id
    for value in [{**CATALOG, "runtime_available": True}, {**CATALOG, "runtime_available": 0}, {**CATALOG, "creation_available": False},
                  {**CATALOG, "profiles": [PROFILE, PROFILE]}, {**CATALOG, "profiles": [{**PROFILE, "pricing": 0}]},
                  {**CATALOG, "profiles": [{**PROFILE, "limits": {**PROFILE["limits"], "max_workers": True}}]},
                  {**CATALOG, "profiles": [{**PROFILE, "gpu_memory_gb": "24"}]}]:
        with pytest.raises(APIResponseValidationError):
            call(mode, value, lambda c: c.serverless.queue.catalog())
