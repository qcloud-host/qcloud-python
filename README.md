<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/qcloud-host/qcloud-python/main/assets/qcloud-wordmark-light.svg">
  <img alt="QCloud" src="https://raw.githubusercontent.com/qcloud-host/qcloud-python/main/assets/qcloud-wordmark.svg" width="220">
</picture>

# QCloud Python

A typed Python client for QCloud inference and generation, with synchronous and asynchronous APIs.

## Install

Python 3.10 or newer. Until the first PyPI release, install from this repository:

```bash
python -m pip install "git+https://github.com/qcloud-host/qcloud-python.git"
```

The prepared distribution is named `qcloud-ai` and imported as `qcloud_ai`. Registry publication is a separate release step.

## First request

Set `QCLOUD_API_KEY` to your QCloud key and `QCLOUD_MODEL` to an active ID from `client.models.list()`.

```python
import os
from qcloud_ai import QCloud

with QCloud() as client:
    response = client.chat.completions.create(
        model=os.environ["QCLOUD_MODEL"],
        messages=[
            {"role": "user", "content": "Explain vector search in one paragraph."}
        ],
    )
    print(response.choices[0].message.content)
```

`QCloudAI` remains available as an alias-compatible class name.

## Streaming

Use a context manager so an early `break` closes the connection.

```python
with QCloud() as client:
    with client.chat.completions.create(
        model=os.environ["QCLOUD_MODEL"],
        messages=[{"role": "user", "content": "Write a short story."}],
        stream=True,
    ) as stream:
        for chunk in stream:
            if chunk.choices:
                print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Async

```python
import asyncio
from qcloud_ai import AsyncQCloud


async def main():
    async with AsyncQCloud() as client:
        result = await client.chat.completions.create(
            model=os.environ["QCLOUD_MODEL"],
            messages=[{"role": "user", "content": "Hello"}],
        )
        print(result.choices[0].message.content)


asyncio.run(main())
```

Async streaming uses `async with await client.chat.completions.create(..., stream=True)` and `async for`. Cancelling the task closes an active stream when used in that context manager.

## Models and embeddings

```python
with QCloud() as client:
    for model in client.models.list().data:
        print(model.id)
    result = client.embeddings.create(
        model=os.environ["QCLOUD_EMBEDDING_MODEL"],
        input=["Search this document"],
    )
    print(result.data[0].embedding)
```

Embedding requests accept `dimensions` and `encoding_format` when supported by the selected model. The default float encoding returns a number list; explicitly selecting `base64` returns a string. The backend rejects unsupported routing/add-on options and checks model capabilities before dispatch.

## Configuration and errors

```python
from qcloud_ai import APIError, APIConnectionError, APITimeoutError, RateLimitError

client = QCloud(timeout=120.0, max_retries=0)
try:
    models = client.models.list()
except APIError as error:
    print(error.status_code, error.request_id)
finally:
    client.close()
```

`api_key` / `QCLOUD_API_KEY` is required. `base_url` / `QCLOUD_BASE_URL` defaults to `https://platform.qcloud.host/api/v1`. For a separate backend deployment, set the full verified API URL including `/v1`; do not infer the API hostname from the website domain. `organization` / `QCLOUD_ORGANIZATION_ID` selects an organization UUID through `X-QCloud-Organization`; an API key can only select the organization that owns it. `timeout` is a per-network-operation timeout in seconds (default 600). `max_retries` defaults to 2. `default_headers` adds custom headers. `http_client` accepts an `httpx.Client` (or `httpx.AsyncClient` for the async client); closing QCloud also closes that injected client.

Typed errors include authentication, permission, billing, missing-model, rate-limit, connection, timeout, server, and response-validation errors. Responses are Pydantic objects; use `model_dump()` for dictionaries.

## Use the official OpenAI SDK

You can also keep an existing OpenAI Chat Completions integration:

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["QCLOUD_API_KEY"], base_url="https://platform.qcloud.host/api/v1"
)
```

Only the endpoints listed below are supported. See [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and [Anthropic's distinct Messages protocol](https://platform.claude.com/docs/en/api/typescript/messages/create).

## Develop

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m build
python -m twine check dist/*
```

See [examples](examples) for tools, JSON output, and asynchronous streaming. Tests use local transports and make no paid model calls.

## API coverage

`client.generation.models.list()`, `.retrieve(id)`, and `.schema(id)` discover the
generation catalog and its captured per-model references. `client.generation.jobs`
supports `submit`, `retrieve`, `result`, `cancel`, `wait`, and `subscribe` for any
schema-defined JSON input/output on queued models. All methods also exist on
`AsyncQCloud`. Catalog models expose `transport`, `queued_available`, and
`schema_available`. References can be OpenAPI or AsyncAPI (`schema_format`), with
`reference_updated_at` dating the capture independently of the catalog refresh.
`schema_issues` reports missing definitions or negotiation contracts without
implying an enabled session route. Check `queued_available` before submitting; WebSocket,
WebRTC, and unknown transports require separate session support and cannot run
through these job helpers.

When present, `model.admission_policy` adds current request restrictions to the
complete model schema. Follow both: a schema can describe settings the service
does not currently accept. The policy lists required fields, permitted values
and whether extra fields are allowed. `model.availability_reason` explains a
policy restriction. Reservations are review thresholds, not guaranteed spending
caps; current prices, billing eligibility and account limits are checked at
submission.

```python
import json
import os
from uuid import uuid4

completed = client.generation.jobs.subscribe(
    model=os.environ["QCLOUD_GENERATION_MODEL"],
    input=json.loads(os.environ["QCLOUD_GENERATION_INPUT"]),
    billing_mode="metered",
    client_request_id=str(uuid4()),  # Persist with the original input.
    timeout=600,
    poll_interval=1,
)
print(completed.result.data)
```

Metered submission explicitly accepts variable charges; there is no guaranteed
spending-cap field. Generation POSTs are never automatically replayed. Reuse the
same UUID and identical body after an ambiguous failure. Typed submission errors
retain `client_request_id`. `GenerationJobError` carries the
failed/cancelled/review job; `GenerationTimeoutError` retains `job_id`.
Async task cancellation and polling timeouts stop the client only; call
`jobs.cancel(id)` explicitly for best-effort server cancellation. Synchronous
polling checks a monotonic deadline and bounds HTTPX network-operation timeouts;
the async client additionally enforces a wall-clock deadline across the request.
`result(id)` returns `GenerationResult` or `GenerationPendingResult`.
New catalog models do not require an SDK update.

Catalog models include `reference_status` (`current`, `retained`, or `unavailable`),
`reference_stale`, and separate `reference_updated_at` / `reference_checked_at`
timestamps. A retained contract keeps its original capture date and creator/license
notices; it is historical documentation, and cannot start new jobs or sessions.
The list response's `catalog` dictionary includes `degraded` and `quarantined_count`
while healthy references continue to refresh. Require `queued_available is True`
before submitting a queued job. Older snapshots may omit provenance fields; the
typed model then uses `None`, which does not establish current availability.

### Upload local model inputs

```python
from pathlib import Path

with QCloud() as client:
    input_file = client.generation.files.upload(
        Path("input.png"), content_type="image/png", max_bytes=32 * 1024 * 1024,
    )
    # Use the reference in the field required by your chosen model's schema.
    model_input = {"image_url": input_file.url}
```

The sync client accepts bytes, paths, binary file handles, or iterables of bytes.
`await async_client.generation.files.upload(...)` accepts bytes, paths, or async
byte iterables. URLs and nonregular paths are rejected. Byte/stream inputs use
`filename="upload.bin"` unless you supply a basename; `content_type` is a bare
MIME type, normalized to lowercase and defaulting to `application/octet-stream`.
Transfers use chunks of at
most 64 KiB and verify the returned size and SHA-256 without buffering the whole
file. SDK-opened paths are closed on exit; caller-owned binary handles stay
open. Consumed generators are closed and should cooperate with cancellation.
Async caller cleanup hooks receive up to 50 ms of grace after the request's
deadline, then cancellation. At most 32 unfinished hooks are retained across
clients; further caller hooks are skipped until capacity is available. Hooks
that suppress cancellation can remain in the background and delay event-loop
shutdown. Python cannot forcibly stop source iteration or cleanup code that
suppresses cancellation or blocks the event loop, so this is not a hard deadline
for the entire process. SDK-owned files are still closed independently.

`max_bytes` defaults to 256 MiB, while the server may apply a lower limit
(default 64 MiB). `size` optionally declares an exact stream length. The default
`timeout=120` is in seconds: sync uses HTTPX's per-network-operation timeout;
async additionally enforces a total deadline and supports task cancellation.
Uploads never retry, including after partial delivery. A lost response may have
left an uploaded file; do not assume failure means nothing was stored.

The `GenerationUploadedFile` receipt contains `id`, `url`, `filename`,
`content_type`, `size_bytes`, `sha256`, `created_at`, and `expires_at`.
Its `qcloud://files/<UUID>` URL is an opaque private input reference resolved by
QCloud for your organization during queued job dispatch. Native WebSocket/WebRTC
messages do not resolve these references. It is not a browser URL or
a provider credential. Expiry limits the QCloud reference's lifetime, not a
guarantee of physical deletion from upstream storage. The backend must enable
uploads and your key needs `generation:invoke`. Uploading does not submit a job
or enable model execution.
Underlying processing storage uses unguessable, publicly readable CDN links.
Private QCloud references and access checks do not make those objects private;
anyone who obtains an upstream link can read its file.

Read an upload's metadata later using its saved UUID:

```python
with QCloud() as client:
    metadata = client.generation.files.retrieve(input_file.id)
    print(metadata.filename, metadata.size_bytes, metadata.expires_at)

# With AsyncQCloud:
# async with AsyncQCloud() as client:
#     metadata = await client.generation.files.retrieve(input_file.id)
```

This requires `generation:read` in the same organization and returns a validated
`GenerationUploadedFile`, not file bytes. Pass a UUID, never a returned URL.
Missing or foreign uploads raise `NotFoundError`; an expired upload raises
`APIError` with `status_code == 410`. The stored SHA-256 describes the uploaded
bytes; a metadata read does not download and hash them again. Both clients accept
`timeout` in seconds; async task cancellation stops an in-flight request.

### Download generated files

Generated media URLs require your QCloud key. Pass the job UUID and the final
asset UUID in that URL to `client.generation.files.download(job_id, asset_id)`.
The SDK builds a route on its configured API origin, never fetching an arbitrary
returned URL or following redirects with your key.

```python
from urllib.parse import urlsplit

# This model's result contains images[].url. Other model schemas may differ.
result = completed.result
asset_id = urlsplit(result.data["images"][0]["url"]).path.rsplit("/", 1)[-1]
job_id = result.job_id
with client.generation.files.download(
    job_id, asset_id, max_bytes=64 * 1024 * 1024, timeout=120
) as file:
    # xb refuses to overwrite an existing file. Choose the path yourself.
    with open("output.bin", "xb") as output:
        for chunk in file:
            output.write(chunk)
```

The async client uses `async with await client.generation.files.download(...)`
and `async for chunk in file`. Always use the context manager, including when
stopping early. Async task cancellation and network errors close the response;
`close()` is also available (await it on an async file).

Each single-use download yields binary chunks of at most 64 KiB and exposes
`content_type`, `content_length`, `content_range`, `accept_ranges`, `status_code`,
`request_id`, and `bytes_read`. It does not select a filename or write files.
`max_bytes` defaults to 256 MiB and can be lowered. `byte_range="bytes=0-1023"`
requests one range; inspect status and range metadata because a server can ignore
the range. As with other Python requests, `timeout` is seconds per network
operation, not a complete-download wall-clock deadline. Use your application's
async timeout when you also need a total deadline. Downloads never retry,
including after partial delivery. Caller-owned output may contain a partial file
on failure; decide whether to retain or remove it.

`client.generation.sessions.create/retrieve/connect/close` manage explicitly
enabled WebSocket/WebRTC sessions. Creation requires metered consent, transport,
and a stable UUID; `max_duration_seconds` defaults to 300. `connect` returns a
single-use capability, not an open socket. Keep tokens/subprotocols in memory
and use the returned `encoding` for native frames. Never reconnect or replay
frames automatically. Check `signaling` as well as `transport`: a WebRTC
capability with `signaling="websocket"` has `websocket_url`, `subprotocols`,
`encoding="msgpack"`, and `protocol="rtc-signaling-v1"`. Use that socket for
the model's signaling messages and a separate peer connection for media. Close
both together and request `sessions.close(id)` during cleanup. Socket closure
alone does not prove remote media stopped or billing was settled. The SDK
returns the typed capability; it does not create or manage media peers.

For native `transport="websocket"` sessions, install the source extra with
`python -m pip install 'qcloud-ai[realtime] @ git+https://github.com/qcloud-host/qcloud-python.git'`
and use the optional raw-message helper:

```python
import json

# session is an existing, explicitly authorized metered WebSocket session.
with client.generation.sessions.open_socket(session.id) as socket:
    # Follow the model's published input/output schema and socket.encoding.
    # JSON models accept text; MessagePack models require caller-encoded bytes.
    socket.send(json.dumps(model_input))  # Only when the model expects JSON text.
    message = socket.recv()  # str for text, bytes for binary; no automatic codec.
print(socket.close_result.billing)  # May still be pending or require review.
```

The async equivalent is `async with await client.generation.sessions.open_socket(id)
as socket`, with `await socket.send(...)`, `await socket.recv()`, and `async for
message in socket`. Both helpers also support iteration until normal closure.
WebRTC signaling capabilities are rejected: this helper does not manage audio,
video, or media peers. It opens one capability and makes one handshake attempt;
redirects, proxy discovery, reconnection, and frame replay are disabled. QCloud
API credentials and custom HTTP headers are never copied into the socket handshake.

The capability must name the same API origin and the exact session socket path.
For an operator-configured separate relay, opt in with a bare trusted
`relay_origin="wss://relay.example.com"`; the SDK verifies the returned URL against
that origin, and never rewrites it. Production sockets require WSS. Plain WS is
accepted only for literal loopback fixtures. Capability tokens stay in memory;
library handshake logging is disabled because subprotocols contain the token.

`open_timeout=10`, `send_timeout=10`, and `close_timeout=5` are seconds, each bounded
to 60. An independent sync shutdown watchdog interrupts a blocked send or close;
async cleanup aborts the transport when a close handshake cannot finish.
`max_message_bytes=16777216` bounds incoming and outgoing messages (UTF-8 bytes for
text); it can only be lowered. `max_queue=4` bounds the library's incoming frame
high-water mark and can be set from 1 to 16. These are flow-control limits, not a
total process-memory cap: an in-flight frame and TLS/OS buffers add overhead.
The async write high-water mark is 32 KiB; only one send may be in flight in either
client. There is no SDK outbound queue. `max_duration_seconds=3600` is a finite
local connection lifetime and can only be lowered; the server can close earlier.
The 30-second capability expiry governs the handshake, not the connected lifetime.

Context exit, normal EOF, transport failure, async cancellation, and the local
lifetime deadline close the socket and request `sessions.close(id)` once without
HTTP retries. `close()` / async `aclose()` are repeat-safe. A successful HTTP close
response is available as `close_result`; inspect its billing status rather than
assuming socket closure settled usage. A cleanup failure raises
`GenerationSocketCleanupError` and remains on `socket.cleanup_error`. If an
application/transport error or cancellation is already in flight, it remains the
primary exception and gains a separate `cleanup_error` attribute. Explicitly
retrieve the session to resolve uncertain cleanup; the helper never resumes it.
If the capability HTTP request itself fails or its basic response cannot be
parsed, its original SDK error is preserved and no socket is opened or closed.
An unused capability expires; the helper does not claim ownership of an unparsed
response. Once a typed capability is returned, stricter socket validation and
handshake failures request HTTP close exactly once. Sync HTTP cleanup retains the
SDK's per-network-operation timeout; it is separate from the socket close deadline.

The optional transport is pinned to `websockets==15.0.1` (Python 3.10+), using its
[sync](https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html) and
[async](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html)
connection APIs. No public realtime availability is implied by installing it.

For `transport="webrtc"` and `signaling="sse"`, use
`with client.generation.sessions.offer(id, sdp=offer,
session_token=capability.token) as events` for WebRTC signaling; the async client
uses `async with await client.generation.sessions.offer(...)`. Keep this stream
open for the session lifetime. Exiting its context releases the connection.
Use a direct backend base URL for long-lived connections. Unexpected EOF and
streamed errors are surfaced; retrieve session status for billing. Real-time
availability requires a configured, verified backend transport and is separate
from catalog presence.

| Resource                                         | Support                                                     |
| ------------------------------------------------ | ----------------------------------------------------------- |
| Chat Completions                                 | Text, streaming, tool-call and structured-output parameters |
| Models                                           | List and retrieve catalog entries                           |
| Embeddings                                       | Create embeddings with a supported model                    |
| Legacy Completions                               | Available when the selected provider/model supports it      |
| Generation models and jobs                      | Schema discovery, arbitrary JSON, durable jobs and polling |
| Generated files                                 | Authenticated binary streaming and single byte ranges       |
| OpenAI Responses, files, audio, realtime         | Not exposed by this SDK/backend release                     |
| Anthropic Messages                              | Backend compatibility endpoint; use the official Anthropic client |

Model availability and features are determined by the QCloud catalog and upstream provider. Use the QCloud model ID, which may differ from the provider's public model ID. The backend also supports `/messages` with Anthropic version `2023-06-01` for compatible text, image, and tool requests. This QCloud SDK has no `messages` resource; use the official Anthropic client with `base_url="https://platform.qcloud.host/api"` (it appends `/v1/messages`) and your QCloud key. Beta features and exact token counting are rejected, so this does not promise full Claude Code compatibility. This library is maintained by QCloud and is not an OpenAI or Anthropic product.

## Serverless queue drafts

`client.serverless.queue.deployments` saves planning records. A draft creates no endpoint, worker, billing account or charge. The catalog may be empty until an operator publishes reviewed profiles; `runtime_available` remains `False`, and `pricing=None` means unknown, never free.

```python
from uuid import uuid4
catalog = client.serverless.queue.catalog()
if catalog.creation_available:
    request_id = str(uuid4())  # Persist with your intent before sending.
    draft = client.serverless.queue.deployments.create(
        name="My model draft", profile_id=catalog.profiles[0].id,
        client_request_id=request_id,
    )
    print(client.serverless.queue.deployments.retrieve(draft.id))
    print(client.serverless.queue.deployments.list().data)
```

`AsyncQCloud` exposes the same methods; `await` each call. Use a scoped QCloud key: `serverless:read` for catalog/list/retrieve and `serverless:manage` for creation. Optional `org_id` selects only the key's own organization; it cannot grant access to another tenant. Every method accepts an optional `timeout` in seconds; asynchronous calls support normal task cancellation.

Create makes one HTTP attempt, even when client retries are enabled. If omitted, the SDK generates `client_request_id` and attaches it as `error.client_request_id` to typed API, connection and response-validation errors. After an ambiguous response, explicitly reuse that UUID with the identical name, profile and organization; the server returns the same draft. Changed intent or actor with the same UUID conflicts. For durable recovery across process termination, generate and store the UUID yourself before calling. QCloud deployment UUIDs are validated, and typed responses expose only the public draft fields. See [the draft example](examples/queue_draft.py).

## Queue runtime (inactive)

The additive `client.serverless.queue.runtime` namespace exposes `capabilities()`, endpoint `quote`, `launch`, `list`, `retrieve`, `stop`, and job `quote`, `create`, `list`, `retrieve`, `result`. `AsyncQCloud` exposes the same methods with `await`. Public capabilities currently return `stage="inactive"`, `execution_available=False`, and `billing_available=False`. Installing this SDK does not enable execution. Quote issuance requires a server-approved profile and metered billing eligibility; prepaid queue admission is not supported by this release.

```python
runtime = client.serverless.queue.runtime
print(runtime.capabilities())
page = runtime.endpoints.list(limit=20)
for endpoint in page.items:
    print(endpoint.id, endpoint.state)
if page.next_cursor is not None:
    runtime.endpoints.list(after_created_at=page.next_cursor.created_at,
                           after_id=page.next_cursor.id)
```

In an authorized environment, persist a request UUID, then call `endpoints.quote(draft_id, client_request_id=request_id)` or `jobs.quote(endpoint_id, client_request_id=request_id, input={"prompt": prompt, "max_tokens": max_tokens})`. A quote creates no worker, model request or funds reservation. Its `estimated_cost_usd` is an exact six-decimal string; `is_spending_cap` is always `False`. Replaying the same intent returns the original quote, even after its `expires_at`; use a new UUID to request a new quote. Use `decimal.Decimal`, not binary floats, if performing arithmetic on the estimate.

Launch with `endpoints.launch(draft_id, quote_id=quote.id, client_request_id=quote.client_request_id)` or submit with `jobs.create(endpoint_id, quote_id=quote.id, client_request_id=quote.client_request_id, input=input)`, preserving the quoted input and organization. Quote, launch, job submission and stop each make one HTTP attempt. Persist the UUID and full intent before sending. An ambiguous failure retains `error.client_request_id`; an explicit replay must reuse the same UUID and intent. Stop reports authoritative `financial_exposure` separately from `released`; repeated cancellation may return `False` / `"none"`. A stop request does not itself prove provider cleanup or a refund.

Lists expose `.items` and `.next_cursor`, with `limit` from 1 to 50 (default 20). `retrieve` returns the requested public record. `jobs.result(endpoint_id, job_id)` returns `.available=False` and `.result=None` until a validated result is available; then `.result` contains `.text`, `.finish_reason`, and token `.usage`. `requires_review` and held exposure may persist after an ambiguous operation. Resource UUIDs, response identity, cursor consistency, UTF-8 prompt/result bounds and usage totals are validated; private provider fields are omitted. Prompt limits are 1–16,384 UTF-8 bytes, and `max_tokens` is 1–4,096; an immutable server profile may impose smaller limits. Optional `org_id` and `timeout` follow the draft resource conventions. Existing queue draft methods remain unchanged.

## Reliability

Read-only GET requests retry connection failures, timeouts, HTTP 408/409/429 and 5xx responses up to twice, with backoff and `Retry-After` support. Inference POST requests retry only HTTP 429 rejections. An ambiguous connection failure, timeout or server error is surfaced without replaying a potentially billable generation. Authentication/billing failures and started streams are never retried. Set `max_retries=0` to disable all retries. A manual retry after an ambiguous failure may incur duplicate usage.

Streaming handles fragmented UTF-8, CRLF/LF events, multiple data lines, error payloads, and `[DONE]`. A connection ending without `[DONE]` raises a response-validation error instead of reporting a truncated response as complete. HTTP errors are checked before returning a stream; HTTP and streamed API errors retain the server request ID. Invalid JSON or an HTML response from a misconfigured endpoint produces a typed error.

## Security and support

Keep `QCLOUD_API_KEY` in a server environment variable, never in browser code, source control, or a public notebook. Use `QCLOUD_BASE_URL` only for endpoints you trust. HTTPS is the production default; HTTP is supported for local testing. Redirects are not followed. An API key, an active catalog model, and a working QCloud inference backend are required for live requests.

[QCloud](https://www.qcloud.host) · [Developer quickstart](https://www.qcloud.host/api-docs) · [Contact](mailto:info@qcloud.host)

MIT licensed. See [LICENSE](LICENSE).
