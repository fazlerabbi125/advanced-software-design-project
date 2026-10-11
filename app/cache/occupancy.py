from redis.asyncio import Redis

from app.utils.constants import OCCUPANCY_CACHE_PREFIX
from app.utils.helpers import build_cache_key


class OccupancyCache:
    def __init__(self, client: Redis) -> None:
        self.client = client

    async def increment(self, zone: str) -> int:
        return await self.client.incr(build_cache_key(OCCUPANCY_CACHE_PREFIX, zone))

    async def decrement(self, zone: str) -> int:
        key = build_cache_key(OCCUPANCY_CACHE_PREFIX, zone)
        count = await self.client.decr(key)
        if count < 0:
            await self.client.set(key, 0)
            return 0
        return count

    async def get(self, zone: str) -> int:
        value = await self.client.get(build_cache_key(OCCUPANCY_CACHE_PREFIX, zone))
        return int(value) if value is not None else 0


async def increment_occupancy(zone: str) -> int:
    from app.cache.redis import get_redis_client

    return await OccupancyCache(await get_redis_client()).increment(zone)


async def decrement_occupancy(zone: str) -> int:
    from app.cache.redis import get_redis_client

    return await OccupancyCache(await get_redis_client()).decrement(zone)
