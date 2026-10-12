from enum import Enum


class CacheKey(Enum):
    OCCUPANCY = ("occupancy", 300)
    OCCUPANCY_LOCK = ("occupancy:lock", 5)

    @property
    def prefix(self) -> str:
        return self.value[0]

    @property
    def ttl_seconds(self) -> int:
        return self.value[1]

    def build(self, *parts: str) -> str:
        normalized_parts = (part.strip().lower() for part in parts if part.strip())
        return ":".join((self.prefix, *normalized_parts))


BOOKING_WINDOW_DAYS = 7
CELERY_QUEUE_NAME = "bfs_gym"
DEFAULT_PAGE_SIZE = 20
MAX_BIOMETRIC_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PAGE_SIZE = 100
MIN_PASSWORD_LENGTH = 12
ALLOWED_BIOMETRIC_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
BIOMETRIC_UPLOAD_CHUNK_BYTES = 1024 * 1024
