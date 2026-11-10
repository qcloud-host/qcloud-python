"""Django views that call QCloud.

Add to a project's ``urls.py``::

    from . import django_views
    urlpatterns = [
        path("chat/", django_views.chat),
        path("chat/stream/", django_views.chat_stream),
    ]

Configure ``QCLOUD_API_KEY`` and ``QCLOUD_MODEL`` in the server environment.
A module-level client is shared by all requests of a worker process and
reuses pooled connections. Under ASGI, use ``AsyncQCloud`` in async views.
"""
from __future__ import annotations

import json
import os

from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from qcloud_ai import APIConnectionError, APIError, QCloud, RateLimitError

MODEL = os.environ.get("QCLOUD_MODEL", "")
_client: QCloud | None = None


def client() -> QCloud:
    global _client
    if _client is None:
        _client = QCloud(timeout=120)
    return _client


def _error(error: Exception) -> JsonResponse:
    if isinstance(error, APIError):
        response = JsonResponse({"error": error.message, "code": error.code},
                                status=error.status_code if error.status_code in (400, 402, 404, 429) else 502)
        response["X-QCloud-Request-ID"] = error.request_id or ""
        if isinstance(error, RateLimitError) and error.retry_after is not None:
            response["Retry-After"] = str(int(error.retry_after))
        return response
    # APIConnectionError: the provider may have started; do not replay automatically.
    return JsonResponse({"error": "Upstream unavailable; check usage before retrying"}, status=503)


def _message(request: HttpRequest) -> str:
    return str(json.loads(request.body or b"{}").get("message", ""))


@csrf_exempt  # server-to-server endpoint; protect it with your own authentication
@require_POST
def chat(request: HttpRequest) -> JsonResponse:
    try:
        reply = client().chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": _message(request)}]
        )
    except (APIError, APIConnectionError) as error:
        return _error(error)
    return JsonResponse({"reply": reply.choices[0].message.content})


@csrf_exempt
@require_POST
def chat_stream(request: HttpRequest):
    try:
        stream = client().chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": _message(request)}], stream=True
        )
    except (APIError, APIConnectionError) as error:
        return _error(error)

    def events():
        # Django closes this generator when the client disconnects, and the
        # context manager then closes the QCloud stream.
        with stream:
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield f"data: {json.dumps({'text': chunk.choices[0].delta.content}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingHttpResponse(events(), content_type="text/event-stream")
