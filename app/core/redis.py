from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global redis_client
    if redis_client is None:
        redis_client = Redis.from_url(get_settings().cache_redis_url, decode_responses=True)
    return redis_client


async def close_redis_client() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None


async def is_cache_redis_available() -> bool:
    try:
        return bool(await get_redis_client().ping())
    except (OSError, RedisError, ValueError):
        return False


async def is_redis_url_available(redis_url: str) -> bool:
    client: Redis | None = None
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        return bool(await client.ping())
    except (OSError, RedisError, ValueError):
        return False
    finally:
        if client is not None:
            await client.aclose()
