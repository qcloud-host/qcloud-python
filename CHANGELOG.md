# Changelog

## 0.4.0 — source candidate, not published

- `APIError` now carries the request ID (`X-Request-ID`, or `request-id` from Messages), response headers, parsed `Retry-After`, reported admission rate limits and the server error code, and keeps the server's error type.
- New `BadRequestError` (400), `ConflictError` (409) and `UnprocessableEntityError` (422), all subclasses of `APIError`.
- POST requests are retried after connection failures that occurred before the request was sent. Ambiguous failures after sending are still never replayed.
- `client.messages` for the supported subset of QCloud's Anthropic Messages bridge, with named-event streaming that ends at `message_stop`.
- Contract tests with the official OpenAI and Anthropic clients; release workflow with build-once artifacts, checksums, provenance attestations and Trusted Publishing.
- Examples for web frameworks and background workers.

## 0.3.0 — source candidate, not published to PyPI

- Sync/async queue planning and inactive runtime resources, including quotes bound to one request UUID and exact decimal estimates.
- Strict resource identity, public response projection and recovery IDs; quote, launch and submission never retry automatically.
- Optional native WebSocket messages with pinned `websockets`, bounded I/O and explicit session/billing cleanup; no automatic reconnection or media peer support.
- Clean wheel installation checks exercise sync/async clients and realtime dependencies outside the source tree.
- Source-only realtime-extra installation and explicit OpenAI/Anthropic compatibility guidance.

- Sync/async local input uploads with bounded streaming, private generation references, verified size/hash receipts and no retries.

- Sync/async generated-file downloads with bounded binary streaming, byte ranges, context-managed cleanup and no automatic retries or file writes.

- OpenAPI/AsyncAPI reference metadata with separately dated captures and explicit documentation gaps.
- Typed WebRTC-over-WebSocket capabilities with native protocol validation in sync/async clients.
- Sync/async session controls, single-use connection capabilities, and WebRTC signaling streams with explicit cleanup.
- Catalog transport classification and incomplete-schema metadata.
- Universal generation catalog/schema discovery and durable job submit/status/result/cancel helpers.
- Sync/async polling, deadline and task-cancellation support, and stable recovery IDs.
- Explicit metered consent and arbitrary JSON inputs/outputs, with no automatic generation POST retries.
- Typed generation jobs, results, pending results, and terminal-state errors.
- Local HTTP generation tests and cross-language backend contract coverage.

## 0.2.0 — earlier source baseline

- Backend HTTP contract tests for Python, TypeScript, streaming, cancellation and organization isolation.
- Explicit organization selection and typed published-model catalog metadata.
- Do not replay potentially billed POST requests after ambiguous failures.
- Reject truncated streams and preserve request IDs on streamed API errors.
- QCloud organization branding and package metadata.
- Functional bounded retries and Retry-After handling.
- HTTP error checks before streaming and typed malformed-response errors.
- SSE framing, Unicode, completion-marker, and cleanup fixes.
- Injectable HTTP transport for local testing.
- Updated usage examples, compatibility boundaries, and CI checks.
