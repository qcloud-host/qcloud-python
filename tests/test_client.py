"""Unit tests for the QCloud AI Python SDK client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from qcloud_ai import (
    QCloudAI,
    AsyncQCloudAI,
    APIError,
    AuthenticationError,
    RateLimitError,
)
from qcloud_ai._base_client import DEFAULT_BASE_URL
from qcloud_ai.types.chat import ChatCompletion
from qcloud_ai.types.completion import Completion
from qcloud_ai.types.embedding import CreateEmbeddingResponse
from qcloud_ai.types.model import ModelList


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    status: int = 200, body: dict[str, Any] | None = None
) -> httpx.Response:
    """Build a fake httpx.Response with JSON body."""
    content = json.dumps(body or {}).encode()
    return httpx.Response(status_code=status, content=content)


CHAT_RESPONSE: dict[str, Any] = {
    "id": "chatcmpl-abc",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}

COMPLETION_RESPONSE: dict[str, Any] = {
    "id": "cmpl-abc",
    "object": "text_completion",
    "created": 1700000000,
    "model": "gpt-3.5-turbo-instruct",
    "choices": [
        {
            "index": 0,
            "text": "Once upon a time",
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
}

EMBEDDING_RESPONSE: dict[str, Any] = {
    "object": "list",
    "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
    "model": "text-embedding-3-small",
    "usage": {"prompt_tokens": 2, "total_tokens": 2},
}

MODELS_RESPONSE: dict[str, Any] = {
    "object": "list",
    "data": [
        {
            "id": "gpt-4o-mini",
            "object": "model",
            "created": 1700000000,
            "owned_by": "qcloud",
        },
    ],
}


# ---------------------------------------------------------------------------
# Client instantiation
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_requires_api_key(self) -> None:
        with pytest.raises(ValueError, match="No API key"):
            QCloudAI(api_key="")

    def test_custom_base_url(self) -> None:
        client = QCloudAI(api_key="qc-test", base_url="https://custom.host/v1")
        assert client.base_url == "https://custom.host/v1"

    def test_default_base_url(self) -> None:
        client = QCloudAI(api_key="qc-test")
        assert client.base_url == DEFAULT_BASE_URL

    def test_env_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QCLOUD_API_KEY", "qc-from-env")
        client = QCloudAI()
        assert client.api_key == "qc-from-env"

    def test_headers_contain_auth(self) -> None:
        client = QCloudAI(api_key="qc-test")
        assert client._headers["Authorization"] == "Bearer qc-test"


# ---------------------------------------------------------------------------
# Chat completions
# ---------------------------------------------------------------------------


class TestChatCompletions:
    @patch.object(httpx.Client, "send")
    def test_create(self, mock_send: MagicMock) -> None:
        mock_send.return_value = _mock_response(200, CHAT_RESPONSE)
        client = QCloudAI(api_key="qc-test")
        result = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert isinstance(result, ChatCompletion)
        assert result.choices[0].message.content == "Hello!"
        assert result.model == "gpt-4o-mini"

    @patch.object(httpx.Client, "send")
    def test_error_401(self, mock_send: MagicMock) -> None:
        mock_send.return_value = _mock_response(
            401, {"error": {"message": "Invalid API key", "type": "auth_error"}}
        )
        client = QCloudAI(api_key="qc-bad")
        with pytest.raises(AuthenticationError):
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
            )

    @patch.object(httpx.Client, "send")
    def test_error_429(self, mock_send: MagicMock) -> None:
        mock_send.return_value = _mock_response(
            429, {"error": {"message": "Rate limited", "type": "rate_limit_error"}}
        )
        client = QCloudAI(api_key="qc-test")
        with pytest.raises(RateLimitError):
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
            )


# ---------------------------------------------------------------------------
# Completions
# ---------------------------------------------------------------------------


class TestCompletions:
    @patch.object(httpx.Client, "send")
    def test_create(self, mock_send: MagicMock) -> None:
        mock_send.return_value = _mock_response(200, COMPLETION_RESPONSE)
        client = QCloudAI(api_key="qc-test")
        result = client.completions.create(
            model="gpt-3.5-turbo-instruct",
            prompt="Once upon",
        )
        assert isinstance(result, Completion)
        assert result.choices[0].text == "Once upon a time"


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class TestEmbeddings:
    @patch.object(httpx.Client, "send")
    def test_create(self, mock_send: MagicMock) -> None:
        mock_send.return_value = _mock_response(200, EMBEDDING_RESPONSE)
        client = QCloudAI(api_key="qc-test")
        result = client.embeddings.create(
            model="text-embedding-3-small",
            input="Hello",
        )
        assert isinstance(result, CreateEmbeddingResponse)
        assert len(result.data) == 1
        assert len(result.data[0].embedding) == 3


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    @patch.object(httpx.Client, "send")
    def test_list(self, mock_send: MagicMock) -> None:
        mock_send.return_value = _mock_response(200, MODELS_RESPONSE)
        client = QCloudAI(api_key="qc-test")
        result = client.models.list()
        assert isinstance(result, ModelList)
        assert result.data[0].id == "gpt-4o-mini"
