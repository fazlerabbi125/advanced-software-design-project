import asyncio
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.utils.constants import ALLOWED_BIOMETRIC_IMAGE_TYPES


class BiometricImageStorage:
    async def save(self, user_id: int, filename: str, content_type: str, content: bytes) -> str:
        settings = get_settings()
        if content_type not in ALLOWED_BIOMETRIC_IMAGE_TYPES:
            raise ValueError("unsupported biometric image type")
        if not content or len(content) > settings.biometric_image_max_bytes:
            raise ValueError("invalid biometric image size")
        suffix = Path(filename).suffix.lower() or ".img"
        key = f"biometrics/{user_id}/{uuid4()}{suffix}"
        destination = settings.upload_root / key
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, content)
        return key
