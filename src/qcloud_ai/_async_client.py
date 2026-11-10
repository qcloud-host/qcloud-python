from __future__ import annotations

import httpx

from typing import Any, Mapping, Optional

from ._base_client import AsyncHTTPClient
from .resources.chat import AsyncChat
from .resources.completions import AsyncCompletions
from .resources.embeddings import AsyncEmbeddings
from .resources.models import AsyncModels
from .resources.generation import AsyncGeneration
from .resources.serverless import AsyncServerless
from .resources.messages import AsyncMessages


class AsyncQCloudAI(AsyncHTTPClient):
    """Asynchronous QCloud AI client — client for QCloud’s OpenAI-compatible inference endpoints.

    Usage::

        from qcloud_ai import AsyncQCloudAI

        client = AsyncQCloudAI(api_key="qc-...")
        response = await client.chat.completions.create(
            model="<active-qcloud-model-id>",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(response.choices[0].message.content)
    """

    chat: AsyncChat
    completions: AsyncCompletions
    embeddings: AsyncEmbeddings
    models: AsyncModels
    generation: AsyncGeneration
    serverless: AsyncServerless
    messages: AsyncMessages

    def __init__(
        self,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        default_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(
            http_client=http_client,
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
        )
        self.chat = AsyncChat(self)
        self.completions = AsyncCompletions(self)
        self.embeddings = AsyncEmbeddings(self)
        self.models = AsyncModels(self)
        self.generation = AsyncGeneration(self)
        self.serverless = AsyncServerless(self)
        self.messages = AsyncMessages(self)
