"""Anthropic-style Messages through QCloud (supported subset).

Run: ``QCLOUD_API_KEY=... QCLOUD_MODEL=... python messages.py``
"""
import os

from qcloud_ai import QCloud

with QCloud() as client:
    message = client.messages.create(
        model=os.environ["QCLOUD_MODEL"],
        max_tokens=256,
        system="Answer in one sentence.",
        messages=[{"role": "user", "content": "What is an embedding?"}],
    )
    print(message.text)
    print("usage:", message.usage.input_tokens, message.usage.output_tokens)

    with client.messages.create(
        model=os.environ["QCLOUD_MODEL"],
        max_tokens=256,
        messages=[{"role": "user", "content": "Count to five."}],
        stream=True,
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta":
                print(event.delta.get("text", ""), end="", flush=True)
            elif event.type == "message_delta":
                print("\nusage:", event.usage)
