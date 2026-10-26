from enum import Enum


class CacheKey(Enum):
    # Visits per zone, kept for a day after the last entry. Named apart from the old
    # "occupancy" counter keys, which hold a different Redis type.
    OCCUPANCY = ("zone-visits", 24 * 60 * 60)
    VIP_WAITLIST = ("vip-waitlist", 24 * 60 * 60)

    @property
    def prefix(self) -> str:
        return self.value[0]

    @property
    def ttl_seconds(self) -> int:
        return self.value[1]

    def build(self, *parts: str) -> str:
        normalized_parts = (part.strip().lower() for part in parts if part.strip())
        return ":".join((self.prefix, *normalized_parts))


# How long a visit counts towards a zone's occupancy before the member is treated as gone.
ZONE_STAY_MINUTES = {
    "gym_floor": 180,
    "vip_sauna": 30,
    "vip_massage": 60,
    "vip_cold_plunge": 15,
}
VIP_ROOM_CAPACITY = 8
# A member who does not come back within this time loses their place on a VIP waiting list.
VIP_WAITLIST_HOLD_MINUTES = 30
# Upper limits for manager-configured plans. Larger values overflow date arithmetic in
# booking and renewal (e.g. now + timedelta(days=...)), or are clearly typos.
MAX_PLAN_PRICE_MINOR = 1_000_000  # EUR 10,000
MAX_PLAN_DURATION_DAYS = 3650
MAX_BOOKING_WINDOW_DAYS = 365
MAX_WEEKLY_BOOKING_LIMIT = 1000
DEFAULT_PAGE_SIZE = 20
HEALTH_CHECK_TIMEOUT_SECONDS = 5
MAX_BIOMETRIC_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PAGE_SIZE = 100
MIN_PASSWORD_LENGTH = 12
ALLOWED_BIOMETRIC_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
BIOMETRIC_UPLOAD_CHUNK_BYTES = 1024 * 1024
