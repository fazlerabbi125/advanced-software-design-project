import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from typing import Protocol
from uuid import UUID

from app.core.config import get_settings
from app.modules.members.photo_validation import PhotoValidator
from app.shared.constants import BIOMETRIC_UPLOAD_CHUNK_BYTES
from app.shared.handle_file import build_filename, delete_file


class UploadStream(Protocol):
    content_type: str | None

    def read(self, size: int = -1) -> Awaitable[bytes]: ...

    def close(self) -> Awaitable[None]: ...


@dataclass(frozen=True, slots=True)
class StoredBiometricImage:
    key: str
    content_type: str


class BiometricImageStorage:
    def __init__(self, validator: PhotoValidator) -> None:
        self.validator = validator

    async def save(self, user_id: UUID, upload: UploadStream) -> StoredBiometricImage:
        settings = get_settings()
        content_type = upload.content_type or ""
        total_size = 0
        promoted = False
        staging: Path | None = None
        try:
            user_directory = settings.upload_root / "biometrics" / str(user_id)
            await asyncio.to_thread(user_directory.mkdir, parents=True, exist_ok=True)
            staging = user_directory / f"{token_hex(16)}.upload"
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
            verified_suffix = await asyncio.to_thread(
                self.validator.validate,
                staging,
                content_type,
            )
            key = f"biometrics/{user_id}/{build_filename(verified_suffix)}"
            destination = settings.upload_root / key
            await asyncio.to_thread(staging.replace, destination)
            promoted = True
        finally:
            if staging is not None and not promoted:
                await asyncio.to_thread(delete_file, staging)
            await upload.close()
        return StoredBiometricImage(key=key, content_type=content_type)
