# Request controls, streaming, and errors

The same methods are available on `QCloud` and `AsyncQCloud`. Set defaults on
the client and override individual requests with `timeout` and `max_retries`:

```python
import os
from qcloud_ai import QCloud

with QCloud(timeout=120, max_retries=2) as client:
    models = client.models.list(timeout=10, max_retries=1)
    response = client.chat.completions.create(
        model=os.environ["QCLOUD_MODEL"],
        messages=[{"role": "user", "content": "Explain embeddings briefly."}],
        timeout=30,
        max_retries=0,
    )
    print(response.choices[0].message.content)
```

These two options configure the HTTP transport; they are never sent as model
parameters. They work on chat completions, legacy completions, embeddings,
Messages, and model listing/retrieval, including async and streaming calls.
Omitting an option or passing `None` uses the client default. `timeout` must be
a positive finite number of seconds; it limits each network operation, not the
total run including retries. `max_retries` is a non-negative integer; zero means
one attempt. Other keyword arguments, such as `temperature` and `max_tokens`,
remain API parameters and must be supported by the endpoint and selected model.

## What is safe to retry

- An HTTP 429 is a rejected admission before provider dispatch. The SDK retries
  it up to `max_retries`, honoring a valid `Retry-After` of up to 60 seconds;
  otherwise it uses capped exponential backoff with jitter.
- A connection or pool failure before request bytes are sent can be retried.
- Read-only GET requests can retry transient 408/409/5xx responses and transport
  failures.
- A POST timeout after sending, a reset while reading, or a 5xx is ambiguous:
  the provider may already have produced billable output. The SDK does not
  replay these POST requests. It also does not restart an interrupted stream.

Avoid wrapping every exception in another automatic retry loop. That can
duplicate requests and charges. See the runnable, fully offline
[`request_controls.py`](../examples/request_controls.py) example for a rejected
admission and its request ID.

## Diagnose without exposing prompts or keys

Catch `APIError` for HTTP errors. Record `status_code`, `code`, and `request_id`;
use `retry_after` and `rate_limit` when handling `RateLimitError`. Share the
request ID with QCloud support rather than your API key or complete payload.
`APIConnectionError` and its subclass `APITimeoutError` describe transport
failures. `APIResponseValidationError` describes invalid JSON, invalid schemas,
or incomplete streams. JSON response validation errors include `status_code`
and `request_id` when supplied by the server. JSON validation error messages do
not include malformed response values, and underlying parser tracebacks are
suppressed so private model data is not included in the displayed traceback.

## Close every stream

Use `with client.chat.completions.create(..., stream=True) as stream` or
`async with await client.chat.completions.create(..., stream=True) as stream`.
The context closes the response on normal completion, an early `break`, an
exception, or async cancellation. Use `stream_options={"include_usage": True}`
to request the final usage chunk. A usage-only chunk can have no choices; check
`chunk.choices` before reading delta text. Breaking early may prevent you from
receiving final usage; check the console for accounting.

[`stream_lifecycle.py`](../examples/stream_lifecycle.py) makes one live request
with bounded output. It needs an API key and an active model, and may incur usage
charges. Closing the local connection is not a promise of server-side billing
cancellation.

## Select a model and verify availability

Read `client.models.list()` and inspect the chosen entry's capabilities before
using tools, images, or embeddings. Do not assume that a model ID from another
provider or an old example is active in QCloud. Model availability and pricing
can change. A generation catalog entry alone does not enable execution, uploads,
realtime, or serverless queue execution; inspect capabilities and see
[`COMPATIBILITY.md`](../COMPATIBILITY.md) for the last verified service state.
The presence of an SDK method is not proof that a production gate is enabled.
