from enum import Enum


class CacheKey(Enum):
    # The occupancy set is kept for a day after the last entry, then Redis clears it.
    OCCUPANCY = ("occupancy", 24 * 60 * 60)

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
# How long a visit counts towards a zone's occupancy before the member is treated as gone.
ZONE_STAY_MINUTES = {
    "gym_floor": 180,
    "vip_sauna": 30,
    "vip_massage": 60,
    "vip_cold_plunge": 15,
}
VIP_ROOM_CAPACITY = 8
CELERY_QUEUE_NAME = "bfs_gym"
DEFAULT_PAGE_SIZE = 20
HEALTH_CHECK_TIMEOUT_SECONDS = 5
MAX_BIOMETRIC_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PAGE_SIZE = 100
MIN_PASSWORD_LENGTH = 12
ALLOWED_BIOMETRIC_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
BIOMETRIC_UPLOAD_CHUNK_BYTES = 1024 * 1024
