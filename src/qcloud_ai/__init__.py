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

from ._async_client import AsyncQCloudAI
from ._base_client import SDK_VERSION as __version__
from ._client import QCloudAI
from ._downloads import GenerationFile, AsyncGenerationFile
from ._exceptions import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    InsufficientCreditsError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    QCloudAIError,
    RateLimitError,
)
from .resources.generation import GenerationJobError, GenerationTimeoutError
from .resources.generation_sessions import (
    AsyncGenerationSessionStream,
    GenerationSessionStream,
)
from .types.generation import (
    GenerationBilling,
    GenerationJob,
    GenerationModel,
    GenerationModelList,
    GenerationPendingResult,
    GenerationResult,
    GenerationSession,
    GenerationSessionConnection,
    GenerationSessionEvent,
    GenerationSubscription,
    GenerationWebRTCConnection,
    GenerationWebRTCSignalingConnection,
    GenerationWebSocketConnection,
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
    "GenerationJobError",
    "GenerationTimeoutError",
    "GenerationModel",
    "GenerationModelList",
    "GenerationBilling",
    "GenerationJob",
    "GenerationResult",
    "GenerationPendingResult",
    "GenerationSubscription",
    "GenerationSession",
    "GenerationSessionConnection",
    "GenerationSessionEvent",
    "GenerationWebSocketConnection",
    "GenerationWebRTCConnection",
    "GenerationWebRTCSignalingConnection",
    "GenerationSessionStream",
    "AsyncGenerationSessionStream",
    "GenerationFile",
    "AsyncGenerationFile",
]

QCloud = QCloudAI
AsyncQCloud = AsyncQCloudAI
