import time

from redis.asyncio import Redis

from app.core.redis import get_redis_client
from app.utils.constants import CacheKey

# Runs inside Redis as a single step, so two people arriving at the same moment
# cannot both take the last free place.
# KEYS[1] = zone set. ARGV = now, visit end time, member id, capacity (0 = no limit), key TTL.
ENTER_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
local capacity = tonumber(ARGV[4])
local already_inside = redis.call('ZSCORE', KEYS[1], ARGV[3])
if capacity > 0 and not already_inside and redis.call('ZCARD', KEYS[1]) >= capacity then
    return -1
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return redis.call('ZCARD', KEYS[1])
"""


class ZoneOccupancy:
    """Live count of the people inside each zone.

    Each zone is a Redis sorted set with one entry per member inside, scored by the
    time their visit runs out. Entries past that time are removed before every count,
    so members are checked out automatically after their stay. A member who enters
    twice is counted once.
    """

    def __init__(self, client: Redis) -> None:
        self.client = client

    async def enter(
        self, zone: str, member_id: int, stay_seconds: int, capacity: int | None = None
    ) -> bool:
        """Hold a place for the member. Returns False when the zone is already full."""
        now = time.time()
        result = await self.client.eval(
            ENTER_SCRIPT,
            1,
            CacheKey.OCCUPANCY.build(zone),
            now,
            now + stay_seconds,
            member_id,
            capacity or 0,
            CacheKey.OCCUPANCY.ttl_seconds,
        )
        return int(result) >= 0

    async def leave(self, zone: str, member_id: int) -> None:
        await self.client.zrem(CacheKey.OCCUPANCY.build(zone), member_id)

    async def count(self, zone: str) -> int:
        key = CacheKey.OCCUPANCY.build(zone)
        async with self.client.pipeline(transaction=True) as pipeline:
            pipeline.zremrangebyscore(key, "-inf", time.time())
            pipeline.zcard(key)
            _, count = await pipeline.execute()
        return int(count)


def get_zone_occupancy() -> ZoneOccupancy:
    return ZoneOccupancy(get_redis_client())
