from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from .._base_client import AsyncHTTPClient, SyncHTTPClient
from .._downloads import AsyncGenerationFile, GenerationFile, MAX_DOWNLOAD_BYTES
from .._exceptions import APIResponseValidationError
from .._uuid import normalize_uuid
from .._uploads import UploadSource, AsyncUploadSource, MAX_UPLOAD_BYTES
from ..types.generation import GenerationUploadedFile


def _uploaded_file(value: Any, expected_id: str) -> GenerationUploadedFile:
    try:
        file = GenerationUploadedFile.model_validate(value["data"], strict=True)
        created = datetime.fromisoformat(file.created_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(file.expires_at.replace("Z", "+00:00"))
        if (file.id != expected_id or file.url != f"qcloud://files/{expected_id}"
                or not file.filename.strip() or file.filename in (".", "..")
                or len(file.filename.encode("utf8")) > 255
                or any(unicodedata.category(char) == "Cc" or char in "/\\" for char in file.filename)
                or len(file.content_type) > 127
                or re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", file.content_type) is None
                or not 1 <= file.size_bytes <= MAX_UPLOAD_BYTES
                or re.fullmatch(r"[a-f0-9]{64}", file.sha256) is None
                or created.tzinfo is None or expires.tzinfo is None or expires <= created):
            raise ValueError("Invalid file metadata")
        return file
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise APIResponseValidationError("Invalid or mismatched uploaded file metadata") from error


def _options(job_id: str, asset_id: str, max_bytes: int, byte_range: str | None) -> tuple[str, str, dict[str, str]]:
    job_id, asset_id = normalize_uuid(job_id, "job ID"), normalize_uuid(asset_id, "asset ID")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_DOWNLOAD_BYTES:
        raise ValueError("max_bytes must be an integer from 1 to 268435456")
    headers = {"Accept": "application/octet-stream", "Accept-Encoding": "identity"}
    if byte_range is not None:
        match = re.fullmatch(r"bytes=([0-9]{1,16})?-([0-9]{1,16})?", byte_range)
        if not match or not any(match.groups()):
            raise ValueError("byte_range must be one valid byte range")
        start, end = (int(value) if value is not None else None for value in match.groups())
        if any(value is not None and value > 2**53 - 1 for value in (start, end)) or (start is None and end == 0) or (start is not None and end is not None and end < start):
            raise ValueError("byte_range must be one valid byte range")
        headers["Range"] = byte_range
    return job_id, asset_id, headers


class GenerationFiles:
    def __init__(self, client: SyncHTTPClient) -> None:
        self._client = client

    def upload(self, source: UploadSource, *, filename: str | None = None,
               content_type: str = "application/octet-stream", size: int | None = None,
               max_bytes: int = MAX_UPLOAD_BYTES, timeout: float = 120) -> GenerationUploadedFile:
        return self._client._upload(source, filename=filename, content_type=content_type,
                                    size=size, max_bytes=max_bytes, timeout=timeout)

    def retrieve(self, file_id: str, *, timeout: float | None = None) -> GenerationUploadedFile:
        """Read an input upload's metadata, without downloading its bytes."""
        file_id = normalize_uuid(file_id, "file ID")
        response = self._client._request("GET", f"/generation/files/{file_id}", timeout=timeout)
        return _uploaded_file(response.json(), file_id)

    def download(self, job_id: str, asset_id: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES,
                 byte_range: str | None = None, timeout: float | None = None) -> GenerationFile:
        job_id, asset_id, headers = _options(job_id, asset_id, max_bytes, byte_range)
        response = self._client._request("GET", f"/generation/jobs/{job_id}/files/{asset_id}",
                                         binary=True, headers=headers, timeout=timeout, max_retries=0)
        try:
            return GenerationFile(response, job_id, asset_id, max_bytes)
        except BaseException:
            response.close()
            raise


class AsyncGenerationFiles:
    def __init__(self, client: AsyncHTTPClient) -> None:
        self._client = client

    async def upload(self, source: AsyncUploadSource, *, filename: str | None = None,
                     content_type: str = "application/octet-stream", size: int | None = None,
                     max_bytes: int = MAX_UPLOAD_BYTES, timeout: float = 120) -> GenerationUploadedFile:
        return await self._client._upload(source, filename=filename, content_type=content_type,
                                          size=size, max_bytes=max_bytes, timeout=timeout)

    async def retrieve(self, file_id: str, *, timeout: float | None = None) -> GenerationUploadedFile:
        """Read an input upload's metadata, without downloading its bytes."""
        file_id = normalize_uuid(file_id, "file ID")
        response = await self._client._request("GET", f"/generation/files/{file_id}", timeout=timeout)
        return _uploaded_file(response.json(), file_id)

    async def download(self, job_id: str, asset_id: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES,
                       byte_range: str | None = None, timeout: float | None = None) -> AsyncGenerationFile:
        job_id, asset_id, headers = _options(job_id, asset_id, max_bytes, byte_range)
        response = await self._client._request("GET", f"/generation/jobs/{job_id}/files/{asset_id}",
                                               binary=True, headers=headers, timeout=timeout, max_retries=0)
        try:
            return AsyncGenerationFile(response, job_id, asset_id, max_bytes)
        except BaseException:
            await response.aclose()
            raise
