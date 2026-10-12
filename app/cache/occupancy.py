from redis.asyncio import Redis

from app.utils.constants import CacheKey


class OccupancyCache:
    def __init__(self, client: Redis) -> None:
        self.client = client

    async def increment(self, zone: str) -> int:
        key = CacheKey.OCCUPANCY.build(zone)
        async with self.client.lock(
            CacheKey.OCCUPANCY_LOCK.build(zone),
            timeout=CacheKey.OCCUPANCY_LOCK.ttl_seconds,
            blocking=False,
            thread_local=False,
        ):
            async with self.client.pipeline(transaction=True) as pipeline:
                pipeline.incr(key)
                pipeline.expire(key, CacheKey.OCCUPANCY.ttl_seconds)
                count, _ = await pipeline.execute()
        return int(count)

    async def decrement(self, zone: str) -> int:
        key = CacheKey.OCCUPANCY.build(zone)
        async with self.client.lock(
            CacheKey.OCCUPANCY_LOCK.build(zone),
            timeout=CacheKey.OCCUPANCY_LOCK.ttl_seconds,
            blocking=False,
            thread_local=False,
        ):
            async with self.client.pipeline(transaction=True) as pipeline:
                pipeline.decr(key)
                pipeline.expire(key, CacheKey.OCCUPANCY.ttl_seconds)
                count, _ = await pipeline.execute()
            if count < 0:
                await self.client.delete(key)
                return 0
        return int(count)

    async def get(self, zone: str) -> int:
        value = await self.client.get(CacheKey.OCCUPANCY.build(zone))
        return int(value) if value is not None else 0


async def increment_occupancy(zone: str) -> int:
    from app.cache.redis import get_redis_client

    return await OccupancyCache(get_redis_client()).increment(zone)


async def decrement_occupancy(zone: str) -> int:
    from app.cache.redis import get_redis_client

    return await OccupancyCache(get_redis_client()).decrement(zone)
