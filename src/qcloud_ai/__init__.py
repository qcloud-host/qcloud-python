"""QCloud AI — Python client for the QCloud LLM inference API.

Usage::

    from qcloud_ai import QCloudAI

    client = QCloudAI(api_key="qc-...")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(response.choices[0].message.content)
"""

from ._client import QCloudAI
from ._async_client import AsyncQCloudAI
from ._base_client import SDK_VERSION as __version__
from ._exceptions import (
    QCloudAIError,
    APIError,
    APIResponseValidationError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InsufficientCreditsError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

__all__ = [
    "__version__",
    "QCloudAI",
    "AsyncQCloudAI",
    "QCloudAIError",
    "APIError",
    "APIResponseValidationError",
    "QCloud",
    "AsyncQCloud",
    "APIConnectionError",
    "APITimeoutError",
    "AuthenticationError",
    "InsufficientCreditsError",
    "InternalServerError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
]

QCloud = QCloudAI
AsyncQCloud = AsyncQCloudAI
