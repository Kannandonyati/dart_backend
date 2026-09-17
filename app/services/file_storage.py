"""Uploaded-file storage — local filesystem today, isolated here so a
later swap to S3/Azure Blob (needed once the API and Celery worker
don't share a filesystem — see Settings.upload_storage_dir) touches
one module, not every call site.
"""

import asyncio
import uuid
from pathlib import Path

from app.core.config import settings


def _storage_root() -> Path:
    root = Path(settings.upload_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_upload(content: bytes, *, suffix: str = ".csv") -> str:
    """Writes `content` to a new file under the storage root and returns
    its path as a string (stored on ImportRun, read back by the Celery
    task — the two must agree on this path, which is exactly why both
    read `settings.upload_storage_dir` rather than a value passed
    around some other way)."""
    path = _storage_root() / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(content)
    return str(path)


def read_upload(path: str) -> bytes:
    return Path(path).read_bytes()


def delete_upload(path: str) -> None:
    Path(path).unlink(missing_ok=True)


async def save_upload_async(content: bytes, *, suffix: str = ".csv") -> str:
    return await asyncio.to_thread(save_upload, content, suffix=suffix)


async def read_upload_async(path: str) -> bytes:
    return await asyncio.to_thread(read_upload, path)


async def delete_upload_async(path: str) -> None:
    await asyncio.to_thread(delete_upload, path)
