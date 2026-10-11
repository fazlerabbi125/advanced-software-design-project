import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.core.config import get_settings
from app.utils.constants import ALLOWED_BIOMETRIC_IMAGE_TYPES, BIOMETRIC_UPLOAD_CHUNK_BYTES


class UploadStream(Protocol):
    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredBiometricImage:
    key: str
    content_type: str


class BiometricImageStorage:
    async def save(self, user_id: int, upload: UploadStream) -> StoredBiometricImage:
        settings = get_settings()
        content_type = upload.content_type or ""
        if content_type not in ALLOWED_BIOMETRIC_IMAGE_TYPES:
            raise ValueError("unsupported biometric image type")
        suffix = Path(upload.filename or "").suffix.lower() or ".img"
        key = f"biometrics/{user_id}/{uuid4()}{suffix}"
        destination = settings.upload_root / key
        staging = destination.with_suffix(f"{destination.suffix}.upload")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        total_size = 0
        try:
            file_handle = await asyncio.to_thread(staging.open, "xb")
            try:
                while chunk := await upload.read(BIOMETRIC_UPLOAD_CHUNK_BYTES):
                    total_size += len(chunk)
                    if total_size > settings.biometric_image_max_bytes:
                        raise ValueError("invalid biometric image size")
                    await asyncio.to_thread(file_handle.write, chunk)
                if total_size == 0:
                    raise ValueError("invalid biometric image size")
            finally:
                await asyncio.to_thread(file_handle.close)
            await asyncio.to_thread(staging.replace, destination)
        except BaseException:
            await asyncio.to_thread(staging.unlink, missing_ok=True)
            raise
        finally:
            await upload.close()
        return StoredBiometricImage(key=key, content_type=content_type)
