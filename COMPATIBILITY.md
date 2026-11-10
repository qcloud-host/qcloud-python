# SDK and client compatibility matrix

Status as of 10 November 2026, backend `83e2c02a` (schema 44) and SDK source
`0.4.0` candidate. This file is identical in the backend repository and both
SDK repositories. The API base URL is `https://platform.qcloud.host/api/v1`.
Applications need only a QCloud API key; provider keys never leave QCloud.

"Contract" means the client was run against the production Express routes,
authentication, admission, reservation and usage code on loopback HTTP, with
local provider and database fixtures (`sdks/contracts`). A contract proves wire
compatibility and accounting order. It does **not** prove live provider access
or live paid settlement; that needs the registry acceptance described in each
SDK's `RELEASING.md`.

## Endpoints

| Area | Endpoint | QCloud Python / TypeScript | Official OpenAI client | Official Anthropic client | Production state |
| --- | --- | --- | --- | --- | --- |
| Model catalog | `GET /models`, `GET /models/{id}` | `models.list/retrieve` | Contract (Node 7.52.0, Python 3.46.0) | n/a | Live. 253 active inference models at the last check, refreshed automatically |
| Chat Completions | `POST /chat/completions` | `chat.completions.create` | Contract | n/a | Deployed under existing auth, rate, reservation and contract checks. Live paid settlement not yet acceptance-tested |
| Chat streaming | `stream: true` (SSE, `[DONE]`) | `Stream` / `AsyncStream`; final chunk carries usage | Contract, including `stream_options.include_usage` | n/a | As above |
| Tools / JSON | `tools`, `tool_choice`, `response_format` | Pass-through | Contract (QCloud SDK) | n/a | Requires a model with `tools` capability |
| Legacy completions | `POST /completions` | `completions.create` | Not contract-tested | n/a | As Chat Completions |
| Embeddings | `POST /embeddings` | `embeddings.create` (float and base64) | Contract (default base64 decoded to floats) | n/a | As Chat Completions |
| Anthropic Messages | `POST /messages` | `messages.create`, named-event streaming | n/a | Contract (TypeScript 1.6.0, Python 2.6.0) | Limited bridge; see below |
| Token counting | `POST /messages/count_tokens` | Not provided | n/a | Returns 400 (contract) | Not supported |
| Generation catalog | `GET /generation/models` | `generation.models` | n/a | n/a | Live discovery: 1,459 entries, 10 quarantined. A catalog entry is not an execution approval |
| Generation jobs | `POST /generation/jobs`, status, result, cancel, files | `generation.jobs.*`, `generation.files.*` | n/a | n/a | Execution and upload gates **off** |
| Generation sessions | `/generation/sessions` (WebSocket, WebRTC) | `generation.sessions.*` | n/a | n/a | Realtime gate **off** |
| Serverless queue | `/serverless/queue/...` | `serverless.queue.*` (drafts, quotes) | n/a | n/a | Draft preview only; execution **closed**, prepaid funding rejected by contract |
| Queue runtime | `/serverless/queue/runtime/...` | `serverless.queue.runtime.*` | n/a | n/a | `stage: inactive`, `execution_available: false` |
| Dedicated serverless | `/serverless/{deploymentId}` as base URL | Any QCloud client with that `base_url` | Same transport | n/a | Serverless gate **off** |
| VPS / GPU instances | `/vps/...` | Not in the SDKs | n/a | n/a | Gate **off** |

Not implemented (requests return 404): OpenAI Responses, Assistants, Threads,
Batch, Files, Fine-tuning, Moderations, Images, Audio and Realtime APIs.
Use Chat Completions for agent loops; QCloud does not provide a managed agent
runtime, filesystem tools or a sandbox.

## Request parameters

Chat Completions accepts `model`, `messages`, `stream`, `stream_options`
(`include_usage` only), `max_tokens`, `max_completion_tokens`, `n`,
`temperature`, `top_p`, `frequency_penalty`, `presence_penalty`, `stop`,
`seed`, `logit_bias`, `logprobs`, `top_logprobs`, `user`, `tools`,
`tool_choice`, `parallel_tool_calls` and `response_format`
(`text`, `json_object`, `json_schema`). Any other field, including provider
routing overrides (`provider`, `models`), `store`, `metadata`, `modalities`,
`audio`, `prediction`, `service_tier` and reasoning controls, fails with
**HTTP 400 before any reservation or provider dispatch**. The API also checks
the model's capabilities (`tools`, `vision`) and context/output limits before
admission. Direct Anthropic catalog models accept a narrower subset.

## Anthropic Messages bridge

Use `https://platform.qcloud.host/api` (no `/v1`) as the official Anthropic SDK
base URL, or `client.messages` in the QCloud SDKs with the normal base URL.
Supported: text and system prompts, images for `vision` models, function
tools with `tool_use`/`tool_result`, `temperature`, `top_p`, positive
`max_tokens`, `metadata.user_id` and named-event streaming whose final
`message_delta` carries exact usage. Rejected with 400 before dispatch:
thinking and signed reasoning blocks, prompt caching, any `anthropic-beta`
header, documents/citations, server or built-in tools, strict/deferred tool
fields, structured-output extensions, effort, `top_k`, non-empty
`stop_sequences`, assistant prefill and `anthropic-version` other than
`2023-06-01`.

**Claude Code is not supported.** It depends on thinking, prompt caching,
effort and beta features the bridge cannot preserve, and on exact token
counting. Do not advertise Claude Code compatibility until native Messages
routing exists and a real Claude Code session test passes.

## Errors

Both SDKs raise typed errors that subclass `APIError`:

| Status | Python | TypeScript |
| --- | --- | --- |
| 400 | `BadRequestError` | `BadRequestError` |
| 401 | `AuthenticationError` | `AuthenticationError` |
| 402 | `InsufficientCreditsError` | `InsufficientCreditsError` |
| 403 | `PermissionDeniedError` | `PermissionDeniedError` |
| 404 | `NotFoundError` | `NotFoundError` |
| 409 | `ConflictError` | `ConflictError` |
| 422 | `UnprocessableEntityError` | `UnprocessableEntityError` |
| 429 | `RateLimitError` | `RateLimitError` |
| 5xx | `InternalServerError` | `InternalServerError` |
| network | `APIConnectionError` / `APITimeoutError` | `APIConnectionError` / `APITimeoutError` |

Every `APIError` carries the QCloud request ID (`X-Request-ID`, or `request-id`
on Messages), the response headers, the parsed `Retry-After` delay in seconds,
the reported admission limits (`X-RateLimit-Limit/Remaining-Requests/Tokens`),
the server error `type` and machine-readable `code`. Python names them
`request_id`, `headers`, `retry_after`, `rate_limit`, `error_type`, `code`;
TypeScript uses `requestID`, `headers`, `retryAfter`, `rateLimit`,
`errorType`, `code`. A stream that reports an error, or ends before `[DONE]`
or `message_stop`, raises instead of returning partial text as success.

Rate-limit values describe QCloud request admission. They are not a guarantee
of a provider's final charge, and cost estimates are not billing limits.

## Retries, timeouts and cancellation

Default: 2 retries, 600 s timeout, exponential backoff with jitter, honouring
`Retry-After` up to 60 s.

| Situation | Retried? |
| --- | --- |
| `429` on any method (rejected at admission, before dispatch) | Yes |
| `408`, `409`, `5xx` on `GET` | Yes |
| `408`, `409`, `5xx` on `POST` | **No** |
| Connection refused, DNS failure, connect timeout (request never sent) | Yes, any method |
| Read timeout, reset or close after the request was sent | `GET` only; **never** `POST` |

A billable `POST` that fails ambiguously may already have reached a provider.
QCloud keeps its reservation for reconciliation; the SDK never replays it
automatically. Retry it yourself only after checking usage, or use a
`client_request_id` where the endpoint supports one (generation jobs, sessions,
queue drafts and quotes): the server deduplicates on it. Chat, completions,
embeddings and Messages do not accept an idempotency key.

Set `max_retries=0` / `maxRetries: 0` on official OpenAI/Anthropic clients when
calling QCloud; their default policies retry some ambiguous POST failures.

Cancellation: closing a Python stream, cancelling its task, breaking a
TypeScript `for await`, or aborting its `AbortSignal` closes the HTTP
connection; QCloud aborts the upstream provider request. Usage already reported
by the provider is still recorded. Clients reuse pooled keep-alive connections;
create one client per process and close it on shutdown.

## Verified by

| Suite | Where |
| --- | --- |
| Python unit tests (3.10, 3.13), sdist/wheel and fresh-install check | PVE build host VM211 |
| TypeScript unit tests, ESM/CJS builds, packed-consumer check | VM211 |
| Backend HTTP contracts (QCloud SDKs and official clients), with disposable Redis | VM211 and backend CI |
| PostgreSQL-backed serverless/queue/generation SDK contracts | Backend CI |
