"""FastAPI service that calls QCloud with one shared async client.

    pip install qcloud-ai fastapi uvicorn
    export QCLOUD_API_KEY=... QCLOUD_MODEL=<active catalog id>
    uvicorn fastapi_app:app

The QCloud key stays on the server. One client per process reuses pooled
connections; it is closed when the application shuts down.
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from qcloud_ai import APIConnectionError, APIError, AsyncQCloud, RateLimitError

MODEL = os.environ.get("QCLOUD_MODEL", "")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Inference POSTs are never replayed after an ambiguous failure; the SDK
    # only retries 429s and connections that failed before sending.
    app.state.qcloud = AsyncQCloud(timeout=120)
    try:
        yield
    finally:
        await app.state.qcloud.close()


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


@app.exception_handler(APIError)
async def qcloud_error(_: Request, error: APIError) -> JSONResponse:
    headers = {"X-QCloud-Request-ID": error.request_id or ""}
    if isinstance(error, RateLimitError) and error.retry_after is not None:
        headers["Retry-After"] = str(int(error.retry_after))
    status = error.status_code if error.status_code in (400, 402, 404, 429) else 502
    return JSONResponse({"error": error.message, "code": error.code}, status_code=status, headers=headers)


@app.exception_handler(APIConnectionError)
async def qcloud_unreachable(_: Request, error: APIConnectionError) -> JSONResponse:
    # The request may or may not have reached a provider: do not retry blindly.
    return JSONResponse({"error": "Upstream unavailable; check usage before retrying"}, status_code=503)


@app.post("/chat")
async def chat(body: ChatRequest, request: Request) -> dict:
    client: AsyncQCloud = request.app.state.qcloud
    reply = await client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": body.message}]
    )
    return {"reply": reply.choices[0].message.content, "usage": reply.usage.model_dump() if reply.usage else None}


@app.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    if not MODEL:
        raise HTTPException(500, "QCLOUD_MODEL is not set")
    client: AsyncQCloud = request.app.state.qcloud
    # Open the upstream stream before responding so HTTP errors map to statuses.
    stream = await client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": body.message}], stream=True
    )

    async def events() -> AsyncIterator[str]:
        # If the browser disconnects, Starlette cancels this generator; the
        # context manager closes the QCloud stream, which aborts the provider.
        async with stream:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield f"data: {json.dumps({'text': chunk.choices[0].delta.content}, ensure_ascii=False)}\n\n"
                if chunk.usage:
                    yield f"data: {json.dumps({'usage': chunk.usage.model_dump()})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
