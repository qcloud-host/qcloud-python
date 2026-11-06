from __future__ import annotations

import httpx

from typing import Any, Mapping, Optional

from ._base_client import SyncHTTPClient
from .resources.chat import Chat
from .resources.completions import Completions
from .resources.embeddings import Embeddings
from .resources.models import Models
from .resources.generation import Generation


class QCloudAI(SyncHTTPClient):
    """Synchronous QCloud AI client — client for QCloud’s OpenAI-compatible inference endpoints.

    Usage::

        from qcloud_ai import QCloudAI

        client = QCloudAI(api_key="qc-...")
        response = client.chat.completions.create(
            model="<active-qcloud-model-id>",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(response.choices[0].message.content)
    """

    chat: Chat
    completions: Completions
    embeddings: Embeddings
    models: Models
    generation: Generation

    def __init__(
        self,
        *,
        http_client: Optional[httpx.Client] = None,
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
        self.chat = Chat(self)
        self.completions = Completions(self)
        self.embeddings = Embeddings(self)
        self.models = Models(self)
        self.generation = Generation(self)
