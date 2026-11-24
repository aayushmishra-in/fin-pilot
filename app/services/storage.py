import asyncio
import uuid
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import UploadFile

from app.core.config import settings

UPLOAD_ROOT = Path(settings.upload_dir)


def _validate_reference(file_reference: str) -> str:
    if "\\" in file_reference or "\x00" in file_reference:
        raise ValueError("Invalid stored file reference")
    path = PurePosixPath(file_reference)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Invalid stored file reference")
    return "/".join(path.parts)


def _supabase_request(
    method: str, file_reference: str, body: bytes | None = None
) -> bytes:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Supabase Storage credentials are not configured")
    reference = _validate_reference(file_reference)
    bucket = quote(settings.supabase_storage_bucket, safe="")
    object_path = quote(reference, safe="/")
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_path}"
    key = settings.supabase_service_role_key.get_secret_value()
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
        headers["x-upsert"] = "false"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 404:
            raise FileNotFoundError("Stored upload was not found") from error
        raise RuntimeError(
            f"Supabase Storage request failed with HTTP {error.code}"
        ) from error
    except URLError as error:
        raise RuntimeError("Supabase Storage request failed") from error


async def save_file(
    upload_file: UploadFile,
    company_id: UUID,
    *,
    extension: str | None = None,
) -> str:
    extension = (
        extension
        if extension is not None
        else Path(upload_file.filename or "").suffix
    )
    file_reference = f"{company_id}/{uuid.uuid4()}{extension}"
    contents = await upload_file.read()

    if settings.storage_backend == "supabase":
        await asyncio.to_thread(_supabase_request, "POST", file_reference, contents)
    elif settings.storage_backend == "local":
        destination = UPLOAD_ROOT / file_reference
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, contents)
    else:
        raise RuntimeError("STORAGE_BACKEND must be 'local' or 'supabase'")

    return file_reference


async def read_file(file_reference: str) -> bytes:
    reference = _validate_reference(file_reference)
    if settings.storage_backend == "supabase":
        return await asyncio.to_thread(_supabase_request, "GET", reference)
    if settings.storage_backend != "local":
        raise RuntimeError("STORAGE_BACKEND must be 'local' or 'supabase'")
    return await asyncio.to_thread(lambda: resolve_file_path(reference).read_bytes())


def get_file_path(file_reference: str) -> Path:
    """Return the path used by the local development storage backend."""
    return UPLOAD_ROOT / _validate_reference(file_reference)


def resolve_file_path(file_reference: str) -> Path:
    """Resolve an existing local file while preventing traversal outside uploads."""
    upload_root = UPLOAD_ROOT.resolve()
    resolved = get_file_path(file_reference).resolve(strict=True)
    try:
        resolved.relative_to(upload_root)
    except ValueError as error:
        raise ValueError("Stored file reference escapes the upload directory") from error
    if not resolved.is_file():
        raise FileNotFoundError("Stored upload is not a regular file")
    return resolved
