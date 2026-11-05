import asyncio
import os
from qcloud_ai import AsyncQCloud


async def main():
    async with AsyncQCloud() as client:
        async with await client.chat.completions.create(
            model=os.environ["QCLOUD_MODEL"],
            messages=[{"role": "user", "content": "Tell me a short story."}],
            stream=True,
        ) as stream:
            async for chunk in stream:
                if chunk.choices:
                    print(chunk.choices[0].delta.content or "", end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
