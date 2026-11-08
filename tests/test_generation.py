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
    AsyncQCloud,
    GenerationJobError,
    GenerationPendingResult,
    GenerationTimeoutError,
    QCloud,
)

MODEL = "qcloud/test/nested"
BILLING = {
    "mode": "metered",
    "status": "settled",
    "currency": "USD",
    "markup_multiplier": 2,
    "cost_usd": 0.012,
}


@pytest.fixture
def generation_server():
    id = str(uuid4())
    state = {
        "posts": [],
        "reads": 0,
        "results": 0,
        "cancels": 0,
        "paths": [],
        "terminal": "succeeded",
        "failure": 0,
        "stall": False,
        "mismatch": False,
    }

    def job(status="queued"):
        return {
            "object": "generation.job",
            "id": str(uuid4()) if state["mismatch"] else id,
            "model": MODEL,
            "status": status,
            "created_at": "2026-11-06T00:00:00Z",
            "updated_at": "2026-11-06T00:00:00Z",
            "completed_at": None,
            "deadline_at": "2026-11-07T00:00:00Z",
            "cancel_requested": False,
            "error": {"code": "execution_failed", "message": "Execution failed"}
            if status == "failed"
            else None,
            "billing": BILLING,
            "result_url": None,
        }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_json(self, value, status=200):
            encoded = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Request-Id", "generation-python-http")
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            state["paths"].append(self.path)
            if self.path.endswith("/cancel"):
                state["cancels"] += 1
                self.send_json({"data": job("cancelled")}, 202)
                return
            data = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
            )
            state["posts"].append(data)
            if state["failure"]:
                self.send_json(
                    {"error": {"type": "fixture_error", "message": "Unavailable"}},
                    state["failure"],
                )
                return
            self.send_json({"data": job()}, 202)

        def do_GET(self):
            state["paths"].append(self.path)
            if "/models" in self.path:
                model = {
                    "id": MODEL,
                    "object": "generation.model",
                    "display_name": "Nested model",
                    "category": "image-to-video",
                    "description": "Fixture",
                    "status": "active",
                    "available": True,
                    "transport": "queue",
                    "queued_available": True,
                    "schema_available": True,
                    "license": {"notice": "Preserve this"},
                    "updated_at": "2026-11-06T00:00:00Z",
                    "schema_url": "/schema",
                    "pricing": None,
                }
                if self.path.endswith("/schema"):
                    self.send_json(
                        {
                            "openapi": "3.1.0",
                            "components": {
                                "schemas": {
                                    "Input": {"$ref": "#/components/schemas/Nested"}
                                }
                            },
                            "x-qcloud-model": model,
                        }
                    )
                elif "qcloud%2Ftest%2Fnested" in self.path:
                    self.send_json(model)
                else:
                    self.send_json(
                        {
                            "object": "list",
                            "data": [model],
                            "has_more": False,
                            "next_cursor": None,
                            "catalog": {
                                "last_updated_at": None,
                                "stale": False,
                                "total": 1,
                            },
                        }
                    )
                return
            if state["stall"]:
                time.sleep(0.3)
            if self.path.endswith("/result"):
                state["results"] += 1
                if state["results"] == 1:
                    self.send_json({"data": job("running")}, 202)
                else:
                    self.send_json(
                        {
                            "job_id": str(uuid4()) if state["mismatch"] else id,
                            "data": [None, True, {"nested": ["🌍", 123]}],
                            "billing": BILLING,
                        }
                    )
                return
            state["reads"] += 1
            self.send_json(
                {"data": job("running" if state["reads"] < 2 else state["terminal"])}
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"id": id, "state": state, "url": f"http://127.0.0.1:{server.server_port}/v1"}
    server.shutdown()
    server.server_close()
    thread.join(timeout=1)


def client(fixture):
    return QCloud(
        api_key="qc-fixture", base_url=fixture["url"], timeout=3, max_retries=3
    )


def test_generation_discovery_preserves_encoded_ids_and_schema(generation_server):
    with client(generation_server) as sdk:
        assert (
            sdk.generation.models.list(q="a b", category="image-to-video", limit=3)
            .data[0]
            .id
            == MODEL
        )
        assert sdk.generation.models.retrieve(MODEL).license == {
            "notice": "Preserve this"
        }
        assert (
            sdk.generation.models.schema(MODEL)["components"]["schemas"]["Input"][
                "$ref"
            ]
            == "#/components/schemas/Nested"
        )
    assert "q=a+b" in generation_server["state"]["paths"][0]
    assert any(
        "qcloud%2Ftest%2Fnested/schema" in path
        for path in generation_server["state"]["paths"]
    )


def test_sync_generation_jobs_preserve_arbitrary_json_and_recovery_id(
    generation_server,
):
    request_id = str(uuid4())
    with client(generation_server) as sdk:
        job = sdk.generation.jobs.submit(
            model=MODEL,
            input=[None, {"arbitrary": True}],
            billing_mode="metered",
            client_request_id=request_id,
        )
        assert job.id == generation_server["id"]
        assert isinstance(sdk.generation.jobs.result(job.id), GenerationPendingResult)
        result = sdk.generation.jobs.subscribe(
            model=MODEL,
            input=None,
            billing_mode="metered",
            timeout=2,
            poll_interval=0.005,
        )
        assert result.result.data == [None, True, {"nested": ["🌍", 123]}]
        assert sdk.generation.jobs.cancel(job.id).status == "cancelled"
    assert generation_server["state"]["posts"][0]["client_request_id"] == request_id
    assert generation_server["state"]["cancels"] == 1


@pytest.mark.parametrize("status", ["failed", "cancelled", "review"])
def test_terminal_errors_carry_job_without_sending_cancel(generation_server, status):
    generation_server["state"]["terminal"] = status
    with client(generation_server) as sdk, pytest.raises(GenerationJobError) as error:
        sdk.generation.jobs.wait(
            generation_server["id"], timeout=2, poll_interval=0.005
        )
    assert error.value.job.status == status
    assert generation_server["state"]["cancels"] == 0


@pytest.mark.parametrize("status", [429, 503])
def test_generation_post_is_never_automatically_replayed(generation_server, status):
    generation_server["state"]["failure"] = status
    request_id = str(uuid4())
    with client(generation_server) as sdk, pytest.raises(APIError) as error:
        sdk.generation.jobs.submit(
            model=MODEL,
            input="arbitrary",
            billing_mode="metered",
            client_request_id=request_id,
        )
    assert error.value.client_request_id == request_id
    assert error.value.request_id == "generation-python-http"
    assert len(generation_server["state"]["posts"]) == 1


def test_sync_wait_deadline_bounds_a_stalled_http_request(generation_server):
    generation_server["state"]["stall"] = True
    with client(generation_server) as sdk:
        started = time.monotonic()
        with pytest.raises(GenerationTimeoutError) as error:
            sdk.generation.jobs.wait(generation_server["id"], timeout=0.03)
        assert time.monotonic() - started < 0.25
        assert error.value.job_id == generation_server["id"]
    assert generation_server["state"]["cancels"] == 0


@pytest.mark.asyncio
async def test_async_generation_deadline_cancellation_and_arbitrary_result(
    generation_server,
):
    async with AsyncQCloud(
        api_key="qc-fixture", base_url=generation_server["url"], timeout=3
    ) as sdk:
        assert (await sdk.generation.models.retrieve(MODEL)).id == MODEL
        result = await sdk.generation.jobs.subscribe(
            model=MODEL,
            input={"nested": [None, True]},
            billing_mode="metered",
            timeout=2,
            poll_interval=0.005,
        )
        assert result.result.data[2]["nested"] == ["🌍", 123]
        generation_server["state"]["stall"] = True
        with pytest.raises(GenerationTimeoutError):
            await sdk.generation.jobs.wait(generation_server["id"], timeout=0.03)
        task = asyncio.create_task(
            sdk.generation.jobs.wait(generation_server["id"], timeout=1)
        )
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert generation_server["state"]["cancels"] == 0


def test_generation_input_and_response_validation(generation_server):
    with client(generation_server) as sdk:
        with pytest.raises(ValueError):
            sdk.generation.jobs.submit(
                model=MODEL, input=float("nan"), billing_mode="metered"
            )
        with pytest.raises(ValueError):
            sdk.generation.jobs.submit(model=MODEL, input={}, billing_mode="free")
        assert not generation_server["state"]["posts"]
        generation_server["state"]["mismatch"] = True
        with pytest.raises(APIResponseValidationError):
            sdk.generation.jobs.wait(generation_server["id"], timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_uppercase_job_uuids_preserve_identity(generation_server, asynchronous):
    id, state = generation_server["id"], generation_server["state"]
    upper = id.upper()
    request_id = "ABCDEF12-3456-4789-ABCD-EF1234567890"
    sdk = (AsyncQCloud if asynchronous else QCloud)(
        api_key="qc-fixture", base_url=generation_server["url"], timeout=3
    )

    async def call(method, *args, **kwargs):
        result = method(*args, **kwargs)
        return await result if asynchronous else result

    params = dict(model=MODEL, input=None, billing_mode="metered", client_request_id=request_id)
    try:
        await call(sdk.generation.jobs.submit, **params)
        assert state["posts"][0]["client_request_id"] == request_id.lower()
        assert (await call(sdk.generation.jobs.retrieve, upper)).id == id
        pending = await call(sdk.generation.jobs.result, upper)
        assert isinstance(pending, GenerationPendingResult) and pending.data.id == id
        assert (await call(sdk.generation.jobs.result, upper)).job_id == id
        assert (await call(sdk.generation.jobs.wait, upper, timeout=2, poll_interval=0.005)).id == id
        assert (await call(sdk.generation.jobs.cancel, upper)).id == id
        assert (await call(sdk.generation.jobs.subscribe, **params, timeout=2, poll_interval=0.005)).job.id == id
        assert all(path.startswith(f"/v1/generation/jobs/{id}") for path in state["paths"] if path != "/v1/generation/jobs")
        assert all(body["client_request_id"] == request_id.lower() for body in state["posts"])
        state["failure"] = 503
        with pytest.raises(APIError) as error:
            await call(sdk.generation.jobs.submit, **params)
        assert error.value.client_request_id == request_id.lower()
        state["mismatch"] = True
        with pytest.raises(APIResponseValidationError):
            await call(sdk.generation.jobs.retrieve, upper)
        with pytest.raises(APIResponseValidationError):
            await call(sdk.generation.jobs.result, upper)
    finally:
        await call(sdk.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_malformed_job_uuids_fail_before_http(generation_server, asynchronous):
    id, state = generation_server["id"], generation_server["state"]
    sdk = (AsyncQCloud if asynchronous else QCloud)(
        api_key="qc-fixture", base_url=generation_server["url"]
    )

    async def call(method, *args, **kwargs):
        result = method(*args, **kwargs)
        return await result if asynchronous else result

    try:
        for invalid in [f"{{{id}}}", id.replace("-", ""), f" {id}", f"{id}\n", f"g{id[1:]}", id[1:]]:
            for method in [sdk.generation.jobs.retrieve, sdk.generation.jobs.cancel, sdk.generation.jobs.result, sdk.generation.jobs.wait]:
                with pytest.raises(ValueError, match="UUID"):
                    await call(method, invalid)
            for method in [sdk.generation.jobs.submit, sdk.generation.jobs.subscribe]:
                with pytest.raises(ValueError, match="UUID"):
                    await call(method, model=MODEL, input=None, billing_mode="metered", client_request_id=invalid)
        assert state["paths"] == []
    finally:
        await call(sdk.close)
