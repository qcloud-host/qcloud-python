"""QCloud AI — Python client for the QCloud LLM inference API.

Usage::

    import os
    from qcloud_ai import QCloud

    with QCloud(api_key=os.environ["QCLOUD_API_KEY"]) as client:
        response = client.chat.completions.create(
            model=os.environ["QCLOUD_MODEL"],
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(response.choices[0].message.content)
"""

from ._async_client import AsyncQCloudAI
from ._base_client import SDK_VERSION as __version__
from ._client import QCloudAI
from ._downloads import GenerationFile, AsyncGenerationFile
from ._session_socket import (
    AsyncGenerationSocket, GenerationSocket, GenerationSocketError,
    GenerationSocketClosed, GenerationSocketCleanupError,
)
from .types.serverless import QueueCatalog, QueueDeployment, QueueDeploymentList, QueueLimits, QueueProfile
from ._exceptions import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InsufficientCreditsError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    QCloudAIError,
    RateLimitError,
    RateLimitInfo,
    UnprocessableEntityError,
)
from .types.message import Message, MessageContentBlock, MessageStreamEvent, MessageUsage
from .resources.generation import GenerationJobError, GenerationTimeoutError
from .resources.generation_sessions import (
    AsyncGenerationSessionStream,
    GenerationSessionStream,
)
from .types.generation import (
    GenerationUploadedFile,
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

from .types.queue_runtime import (QueueRuntimeQuote, QueueRuntimeCapabilities, QueueRuntimeCursor, QueueRuntimeEndpoint, QueueRuntimeEndpointList, QueueRuntimeJob, QueueRuntimeJobList, QueueRuntimeResult, QueueRuntimeStopResult, QueueRuntimeTextResult, QueueRuntimeUsage)

__all__ = [
    "GenerationSocket", "AsyncGenerationSocket", "GenerationSocketError",
    "GenerationSocketClosed", "GenerationSocketCleanupError",
    "QueueRuntimeQuote", "QueueRuntimeCapabilities", "QueueRuntimeCursor", "QueueRuntimeEndpoint", "QueueRuntimeEndpointList", "QueueRuntimeJob", "QueueRuntimeJobList", "QueueRuntimeResult", "QueueRuntimeStopResult", "QueueRuntimeTextResult", "QueueRuntimeUsage",
    "QueueCatalog", "QueueDeployment", "QueueDeploymentList", "QueueLimits", "QueueProfile",
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
    "RateLimitInfo",
    "BadRequestError",
    "ConflictError",
    "UnprocessableEntityError",
    "Message",
    "MessageContentBlock",
    "MessageStreamEvent",
    "MessageUsage",
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
    "GenerationUploadedFile",
]

QCloud = QCloudAI
AsyncQCloud = AsyncQCloudAI
