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

`api_key` / `QCLOUD_API_KEY` is required. `base_url` / `QCLOUD_BASE_URL` defaults to `https://www.qcloud.host/api/v1`. For a separate backend deployment, set the full verified API URL including `/v1`; do not infer the API hostname from the website domain. `organization` / `QCLOUD_ORGANIZATION_ID` selects an organization UUID through `X-QCloud-Organization`; an API key can only select the organization that owns it. `timeout` is a per-network-operation timeout in seconds (default 600). `max_retries` defaults to 2. `default_headers` adds custom headers. `http_client` accepts an `httpx.Client` (or `httpx.AsyncClient` for the async client); closing QCloud also closes that injected client.

Typed errors include authentication, permission, billing, missing-model, rate-limit, connection, timeout, server, and response-validation errors. Responses are Pydantic objects; use `model_dump()` for dictionaries.

## Use the official OpenAI SDK

You can also keep an existing OpenAI Chat Completions integration:

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["QCLOUD_API_KEY"], base_url="https://www.qcloud.host/api/v1"
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
generation catalog and its complete per-model contracts. `client.generation.jobs`
supports `submit`, `retrieve`, `result`, `cancel`, `wait`, and `subscribe` for any
schema-defined JSON input/output on queued models. All methods also exist on
`AsyncQCloud`. Catalog models expose `transport`, `queued_available`, and
`schema_available`. References can be OpenAPI or AsyncAPI (`schema_format`), with
`reference_updated_at` dating the capture independently of the catalog refresh.
`schema_issues` reports missing definitions or negotiation contracts without
implying an enabled session route. Check `queued_available` before submitting; WebSocket,
WebRTC, and unknown transports require separate session support and cannot run
through these job helpers.

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
| OpenAI Responses, files, audio, realtime         | Not exposed by this SDK/backend release                     |
| Anthropic Messages                              | Backend compatibility endpoint; use the official Anthropic client |

Model availability and features are determined by the QCloud catalog and upstream provider. Use the QCloud model ID, which may differ from the provider's public model ID. The backend also supports `/messages` with Anthropic version `2023-06-01` for compatible text, image, and tool requests. This QCloud SDK has no `messages` resource; use the official Anthropic client with `base_url="https://www.qcloud.host/api"` (it appends `/v1/messages`) and your QCloud key. Beta features and exact token counting are rejected, so this does not promise full Claude Code compatibility. This library is maintained by QCloud and is not an OpenAI or Anthropic product.

## Reliability

Read-only GET requests retry connection failures, timeouts, HTTP 408/409/429 and 5xx responses up to twice, with backoff and `Retry-After` support. Inference POST requests retry only HTTP 429 rejections. An ambiguous connection failure, timeout or server error is surfaced without replaying a potentially billable generation. Authentication/billing failures and started streams are never retried. Set `max_retries=0` to disable all retries. A manual retry after an ambiguous failure may incur duplicate usage.

Streaming handles fragmented UTF-8, CRLF/LF events, multiple data lines, error payloads, and `[DONE]`. A connection ending without `[DONE]` raises a response-validation error instead of reporting a truncated response as complete. HTTP errors are checked before returning a stream; HTTP and streamed API errors retain the server request ID. Invalid JSON or an HTML response from a misconfigured endpoint produces a typed error.

## Security and support

Keep `QCLOUD_API_KEY` in a server environment variable, never in browser code, source control, or a public notebook. Use `QCLOUD_BASE_URL` only for endpoints you trust. HTTPS is the production default; HTTP is supported for local testing. Redirects are not followed. An API key, an active catalog model, and a working QCloud inference backend are required for live requests.

[QCloud](https://www.qcloud.host) · [Developer quickstart](https://www.qcloud.host/api-docs) · [Contact](mailto:info@qcloud.host)

MIT licensed. See [LICENSE](LICENSE).
