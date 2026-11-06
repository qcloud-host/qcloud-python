# Changelog

## Unreleased

- OpenAPI/AsyncAPI reference metadata with separately dated captures and explicit documentation gaps.
- Typed WebRTC-over-WebSocket capabilities with native protocol validation in sync/async clients.
- Sync/async session controls, single-use connection capabilities, and WebRTC signaling streams with explicit cleanup.
- Catalog transport classification and incomplete-schema metadata.
- Universal generation catalog/schema discovery and durable job submit/status/result/cancel helpers.
- Sync/async polling, deadline and task-cancellation support, and stable recovery IDs.
- Explicit metered consent and arbitrary JSON inputs/outputs, with no automatic generation POST retries.
- Typed generation jobs, results, pending results, and terminal-state errors.
- Local HTTP generation tests and cross-language backend contract coverage.

## 0.2.0

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
