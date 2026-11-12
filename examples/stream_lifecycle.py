"""Stream a short paid response. Set QCLOUD_API_KEY and QCLOUD_MODEL first."""

import os

from qcloud_ai import APIConnectionError, APIError, APIResponseValidationError, QCloud


def main() -> None:
    try:
        with QCloud() as client:
            with client.chat.completions.create(
                model=os.environ["QCLOUD_MODEL"],
                messages=[
                    {"role": "user", "content": "Explain an API in one sentence."}
                ],
                max_tokens=64,
                stream=True,
                stream_options={"include_usage": True},
                timeout=30,
                max_retries=0,
            ) as stream:
                for chunk in stream:
                    if chunk.choices:
                        print(chunk.choices[0].delta.content or "", end="", flush=True)
                    if chunk.usage:
                        print("\nReported usage:", chunk.usage.model_dump())
                    # An early break here is safe: the context closes the connection.
            print()
    except APIError as error:
        print(f"HTTP {error.status_code}; request ID: {error.request_id}")
        raise
    except (APIConnectionError, APIResponseValidationError):
        # The model may already have generated billable output. Do not replay blindly.
        print(
            "The response was interrupted; inspect usage before submitting another request."
        )
        raise


if __name__ == "__main__":
    main()
