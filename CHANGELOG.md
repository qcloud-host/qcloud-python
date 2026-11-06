# Changelog

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
