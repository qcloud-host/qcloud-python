"""Run without a key: python examples/request_controls.py (mocked, no paid calls)."""

import httpx

from qcloud_ai import APIError, QCloud, RateLimitError


def main() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            json={
                "error": {"message": "Example admission limit", "code": "rate_limit"}
            },
            headers={"retry-after": "0", "x-request-id": "example-request-123"},
        )

    with QCloud(
        api_key="example-only",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        try:
            client.chat.completions.create(
                model="example-model",
                messages=[{"role": "user", "content": "Hello"}],
                timeout=10,
                max_retries=1,  # One initial attempt plus one safe admission retry.
            )
        except RateLimitError as error:
            print(f"Attempts: {attempts}; retry after: {error.retry_after}s")
            print(f"Request ID for support: {error.request_id}")
        except APIError as error:
            print(f"HTTP {error.status_code}; request ID: {error.request_id}")
    assert attempts == 2


if __name__ == "__main__":
    main()
