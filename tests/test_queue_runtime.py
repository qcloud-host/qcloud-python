from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from qcloud_ai import APIConnectionError, APIError, APIResponseValidationError, AsyncQCloud, QCloud

ORG, DRAFT, EID, JID, QUOTE = [str(uuid4()) for _ in range(5)]
TIME = "2026-11-09T00:00:00.123456+00:00"
ENDPOINT = dict(id=EID, draft_id=DRAFT, generation=1, profile_id="fixture-small", model="Example/Model", state="ready",
                created_at=TIME, deleted_at=None, financial_exposure="held", requires_review=False)
JOB = dict(id=JID, endpoint_id=EID, state="submitted", created_at=TIME, finished_at=None, result_available=False,
           financial_exposure="held", requires_review=True)
RESULT = dict(available=True, result=dict(text="Hello", finish_reason="stop", usage=dict(input_tokens=3, output_tokens=2, total_tokens=5)))
INPUT = dict(prompt="Hello", max_tokens=8)


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def mode(request):
    return request.param


def call(mode, value, operation, status=200, calls=None):
    calls = [] if calls is None else calls
    def handler(request):
        calls.append(request)
        if isinstance(value, Exception):
            raise value
        return httpx.Response(status, json=value)
    if mode:
        async def run():
            async with AsyncQCloud(api_key="qc-fixture", base_url="http://127.0.0.1:1/v1", organization=ORG, max_retries=9,
                                   http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as c:
                return await operation(c.serverless.queue.runtime)
        result = asyncio.run(run())
    else:
        with QCloud(api_key="qc-fixture", base_url="http://127.0.0.1:1/v1", organization=ORG, max_retries=9,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler))) as c:
            result = operation(c.serverless.queue.runtime)
    return result, calls


@pytest.mark.parametrize("kind", ["endpoint", "job"])
@pytest.mark.parametrize("amount", ["0.000001", "12.340000", "9007199254.740991"])
def test_quote_binding_decimal_and_public_projection(mode, kind, amount):
    request_id, target = str(uuid4()), DRAFT if kind == "endpoint" else EID
    expected = dict(id=QUOTE, client_request_id=request_id, kind=kind, target_id=target, expires_at=TIME,
                    currency="USD", estimated_cost_usd=amount, funding_mode="metered", is_spending_cap=False)
    operation = (lambda r: r.endpoints.quote(DRAFT.upper(), client_request_id=request_id, org_id=ORG)) if kind == "endpoint" else (
        lambda r: r.jobs.quote(EID, client_request_id=request_id, org_id=ORG, input=INPUT))
    result, calls = call(mode, {"data": {**expected, "provider_price": "private"}}, operation, 201)
    assert result.model_dump() == expected
    assert json.loads(calls[0].content) == {"client_request_id": request_id, "org_id": ORG, **({"input": INPUT} if kind == "job" else {})}
    assert str(calls[0].url).endswith(f"/deployments/{DRAFT}/quote" if kind == "endpoint" else f"/endpoints/{EID}/jobs/quote")


def test_quotes_reject_coercion_binding_errors_and_cap_claims(mode):
    request_id = str(uuid4())
    expected = dict(id=QUOTE, client_request_id=request_id, kind="endpoint", target_id=DRAFT, expires_at=TIME,
                    currency="USD", estimated_cost_usd="1.000000", funding_mode="metered", is_spending_cap=False)
    patches = [dict(estimated_cost_usd=amount) for amount in ["0.000000", "-1.000000", "1", "1.0", "01.000000", "1e0",
               "9007199254.740992", "10000000000.000000", 1, None, "1.000000\n"]]
    patches += [dict(id="bad"), dict(target_id=EID), dict(client_request_id=str(uuid4())), dict(kind="job"), dict(currency="EUR"),
                dict(funding_mode="prepaid"), dict(is_spending_cap=True), dict(is_spending_cap=0), dict(expires_at="2026-02-30T00:00:00Z")]
    for patch in patches:
        with pytest.raises(APIResponseValidationError) as raised:
            call(mode, {"data": {**expected, **patch}}, lambda r: r.endpoints.quote(DRAFT, client_request_id=request_id))
        assert raised.value.client_request_id == request_id


@pytest.mark.parametrize("status", [409, 429, 503])
@pytest.mark.parametrize("is_job", [False, True])
def test_quotes_never_retry_and_keep_generated_identity(mode, status, is_job):
    calls = []
    operation = (lambda r: r.jobs.quote(EID, input=INPUT)) if is_job else lambda r: r.endpoints.quote(DRAFT)
    with pytest.raises(APIError) as raised:
        call(mode, {"error": {"message": "fixture"}}, operation, status, calls)
    assert len(calls) == 1 and len(raised.value.client_request_id) == 36


def test_quote_input_rejected_before_http(mode):
    calls = []
    for input in [dict(prompt="", max_tokens=1), dict(prompt="ok", max_tokens=0), dict(prompt="ok", max_tokens=True),
                  dict(prompt="ok", max_tokens=1, secret=True)]:
        with pytest.raises(ValueError):
            call(mode, {}, lambda r: r.jobs.quote(EID, input=input), calls=calls)
    with pytest.raises(ValueError):
        call(mode, {}, lambda r: r.endpoints.launch(DRAFT, quote_id=None), calls=calls)
    assert calls == []


def test_inactive_capabilities_and_projection(mode):
    expected = dict(stage="inactive", execution_available=False, billing_available=False)
    result, calls = call(mode, {**expected, "provider": "private"}, lambda r: r.capabilities(org_id=ORG.upper()))
    assert result.model_dump() == expected
    assert str(calls[0].url).endswith(f"/runtime/capabilities?org_id={ORG}")
    assert calls[0].headers["x-qcloud-organization"] == ORG
    for value in [{**expected, "execution_available": True}, {**expected, "billing_available": 0}, {**expected, "stage": "active"}]:
        with pytest.raises(APIResponseValidationError):
            call(mode, value, lambda r: r.capabilities())


def test_launch_submit_identity_and_public_fields(mode):
    result, calls = call(mode, {"data": {**ENDPOINT, "provider_endpoint_id": "private"}},
                         lambda r: r.endpoints.launch(DRAFT.upper(), quote_id=QUOTE.upper(), org_id=ORG), 201)
    assert result.model_dump() == ENDPOINT
    body = json.loads(calls[0].content)
    assert body == dict(quote_id=QUOTE, client_request_id=body["client_request_id"], org_id=ORG)
    assert len(body["client_request_id"]) == 36
    assert str(calls[0].url).endswith(f"/deployments/{DRAFT}/launch")
    result, calls = call(mode, {"data": {**JOB, "provider_job_id": "private"}},
                         lambda r: r.jobs.create(EID, quote_id=QUOTE, client_request_id=body["client_request_id"], input=INPUT))
    assert result.model_dump() == JOB
    assert json.loads(calls[0].content) == dict(quote_id=QUOTE, client_request_id=body["client_request_id"], input=INPUT)


@pytest.mark.parametrize("status", [409, 429, 503])
@pytest.mark.parametrize("resource", ["launch", "job", "stop"])
def test_mutations_never_retry_and_preserve_recovery_identity(mode, status, resource):
    request_id, calls = str(uuid4()), []
    operation = (lambda r: r.endpoints.launch(DRAFT, quote_id=QUOTE, client_request_id=request_id)) if resource == "launch" else (
        (lambda r: r.jobs.create(EID, quote_id=QUOTE, input=INPUT, client_request_id=request_id)) if resource == "job" else lambda r: r.endpoints.stop(EID))
    with pytest.raises(APIError) as raised:
        call(mode, {"error": {"message": "fixture", "code": "request_conflict"}}, operation, status, calls)
    assert raised.value.status_code == status and len(calls) == 1
    if resource != "stop":
        assert raised.value.client_request_id == request_id


def test_connection_error_keeps_generated_identity(mode):
    calls = []
    with pytest.raises(APIConnectionError) as raised:
        call(mode, httpx.ConnectError("lost acknowledgement"), lambda r: r.jobs.create(EID, quote_id=QUOTE, input=INPUT), calls=calls)
    assert len(raised.value.client_request_id) == 36 and len(calls) == 1


def test_pagination_multi_item_cursor_and_projection(mode):
    second = {**ENDPOINT, "id": str(uuid4())}
    cursor = dict(id=second["id"], created_at=TIME)
    result, calls = call(mode, dict(items=[{**ENDPOINT, "registry": "private"}, second], next_cursor={**cursor, "secret": True}),
                         lambda r: r.endpoints.list(limit=2, after_created_at=TIME, after_id=EID, org_id=ORG))
    assert result.model_dump() == dict(items=[ENDPOINT, second], next_cursor=cursor)
    assert calls[0].url.params["after_created_at"] == TIME and calls[0].url.params["limit"] == "2"
    result, _ = call(mode, dict(items=[JOB], next_cursor=None), lambda r: r.jobs.list(EID))
    assert result.items[0].model_dump() == JOB
    for value in [dict(items=[ENDPOINT, ENDPOINT], next_cursor=None), dict(items=[ENDPOINT], next_cursor=cursor), dict(items=[], next_cursor=cursor)]:
        with pytest.raises(APIResponseValidationError):
            call(mode, value, lambda r: r.endpoints.list())
    with pytest.raises(APIResponseValidationError):
        call(mode, dict(items=[ENDPOINT, second], next_cursor=None), lambda r: r.endpoints.list(limit=1))
    with pytest.raises(APIResponseValidationError):
        call(mode, dict(items=[{**JOB, "endpoint_id": str(uuid4())}], next_cursor=None), lambda r: r.jobs.list(EID))


def test_retrieve_and_create_verify_requested_identity(mode):
    result, _ = call(mode, dict(data=ENDPOINT), lambda r: r.endpoints.retrieve(EID.upper()))
    assert result.model_dump() == ENDPOINT
    result, _ = call(mode, dict(data=JOB), lambda r: r.jobs.retrieve(EID, JID))
    assert result.model_dump() == JOB
    for value, operation in [(dict(data=ENDPOINT), lambda r: r.endpoints.retrieve(str(uuid4()))),
                             (dict(data=JOB), lambda r: r.jobs.retrieve(EID, str(uuid4())))]:
        with pytest.raises(APIResponseValidationError):
            call(mode, value, operation)
    request_id = str(uuid4())
    with pytest.raises(APIResponseValidationError) as raised:
        call(mode, dict(data=ENDPOINT), lambda r: r.endpoints.launch(str(uuid4()), quote_id=QUOTE, client_request_id=request_id))
    assert raised.value.client_request_id == request_id


@pytest.mark.parametrize("released,exposure", [(True, "none"), (False, "none"), (False, "held")])
def test_stop_authoritative_exposure_and_repeat_cancellation(mode, released, exposure):
    expected = dict(released=released, financial_exposure=exposure)
    result, calls = call(mode, {**expected, "reservation": "private"}, lambda r: r.endpoints.stop(EID, org_id=ORG))
    assert result.model_dump() == expected and json.loads(calls[0].content) == dict(org_id=ORG)
    with pytest.raises(APIResponseValidationError):
        call(mode, dict(released=True, financial_exposure="held"), lambda r: r.endpoints.stop(EID))


def test_bounded_results_and_pending_privacy(mode):
    result, _ = call(mode, {**RESULT, "result": {**RESULT["result"], "provider": "private"}}, lambda r: r.jobs.result(EID, JID))
    assert result.model_dump() == RESULT
    pending, _ = call(mode, dict(available=False, result=dict(private=True)), lambda r: r.jobs.result(EID, JID))
    assert pending.available is False and pending.result is None
    invalid = [dict(available=True), {**RESULT, "result": {**RESULT["result"], "text": "😀" * 16385}},
               {**RESULT, "result": {**RESULT["result"], "text": "\0"}},
               {**RESULT, "result": {**RESULT["result"], "usage": dict(input_tokens=3, output_tokens=2, total_tokens=6)}},
               {**RESULT, "result": {**RESULT["result"], "usage": dict(input_tokens=0, output_tokens=4097, total_tokens=4097)}}]
    for value in invalid:
        with pytest.raises(APIResponseValidationError):
            call(mode, value, lambda r: r.jobs.result(EID, JID))


def test_job_result_state_and_calendar_dates(mode):
    for value in [{**JOB, "result_available": True}, {**JOB, "created_at": "2026-02-30T00:00:00Z"}, {**JOB, "finished_at": "2026-02-30T00:00:00Z"}]:
        with pytest.raises(APIResponseValidationError):
            call(mode, dict(data=value), lambda r: r.jobs.retrieve(EID, JID))
    value = {**JOB, "state": "completed", "result_available": True}
    result, _ = call(mode, dict(data=value), lambda r: r.jobs.retrieve(EID, JID))
    assert result.model_dump() == value


def test_invalid_requests_fail_before_http_with_recovery_id(mode):
    calls = []
    for input in [dict(prompt="", max_tokens=1), dict(prompt="😀" * 4097, max_tokens=1), dict(prompt="\ud800", max_tokens=1),
                  dict(prompt="\0", max_tokens=1), dict(prompt="ok", max_tokens=True), dict(prompt="ok", max_tokens=4097),
                  dict(prompt="ok", max_tokens=1, secret=True)]:
        with pytest.raises(ValueError) as raised:
            call(mode, dict(data=JOB), lambda r: r.jobs.create(EID, quote_id=QUOTE, input=input), calls=calls)
        assert len(raised.value.client_request_id) == 36
    for params in [dict(limit=0), dict(limit=51), dict(after_id=EID), dict(after_created_at=TIME), dict(after_id=EID, after_created_at="today")]:
        with pytest.raises(ValueError):
            call(mode, {}, lambda r: r.endpoints.list(**params), calls=calls)
    with pytest.raises(ValueError):
        call(mode, {}, lambda r: r.endpoints.retrieve("https://evil.example"), calls=calls)
    assert calls == []


def test_runtime_uuid_version_variant_and_nil_rejected(mode):
    for invalid in ["00000000-0000-0000-0000-000000000000", "11111111-1111-9111-8111-111111111111", "11111111-1111-4111-7111-111111111111"]:
        calls = []
        with pytest.raises(ValueError):
            call(mode, {}, lambda r: r.endpoints.launch(DRAFT, quote_id=invalid), calls=calls)
        with pytest.raises(ValueError):
            call(mode, {}, lambda r: r.endpoints.retrieve(invalid), calls=calls)
        assert calls == []
        with pytest.raises(APIResponseValidationError):
            call(mode, dict(data={**ENDPOINT, "draft_id": invalid}), lambda r: r.endpoints.retrieve(EID))
        with pytest.raises(APIResponseValidationError):
            call(mode, dict(data={**JOB, "id": invalid}), lambda r: r.jobs.retrieve(EID, JID))
