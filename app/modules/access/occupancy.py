import time
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from redis.asyncio import Redis

from app.core.redis import get_redis_client
from app.shared.constants import VIP_WAITLIST_HOLD_MINUTES, CacheKey

# Runs inside Redis as a single step, so two people arriving at the same moment
# cannot both take the last free place, and nobody can jump the waiting list.
# KEYS[1] = zone visits, KEYS[2] = zone waiting list.
# ARGV = now, visit end time, member id, capacity (0 = no limit), key TTL, waiting-list hold.
# Returns 1 when the member is let in, 0 when they were already inside (their visit is
# extended), and -N when the zone is full and they are number N on the waiting list.
ENTER_SCRIPT = """
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZSCORE', KEYS[1], ARGV[3]) then
    redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
    return 0
end
local capacity = tonumber(ARGV[4])
if capacity > 0 then
    redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - tonumber(ARGV[6]))
    local free = capacity - redis.call('ZCARD', KEYS[1])
    local rank = redis.call('ZRANK', KEYS[2], ARGV[3])
    local ahead = rank or redis.call('ZCARD', KEYS[2])
    if free <= ahead then
        if not rank then
            redis.call('ZADD', KEYS[2], now, ARGV[3])
            redis.call('EXPIRE', KEYS[2], ARGV[5])
        end
        return -(ahead + 1)
    end
    redis.call('ZREM', KEYS[2], ARGV[3])
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


class EntryOutcome(StrEnum):
    ADMITTED = "admitted"
    ALREADY_INSIDE = "already_inside"
    WAITLISTED = "waitlisted"


@dataclass(frozen=True, slots=True)
class Entry:
    outcome: EntryOutcome
    waitlist_position: int | None = None


class ZoneOccupancy:
    """Live count of the people inside each zone, and the waiting list for full rooms.

    Each zone is a Redis sorted set with one entry per member inside, scored by the
    time their visit runs out. Entries past that time are removed before every count,
    so members are checked out automatically after their stay. A member who enters
    twice is counted once.

    A room with a capacity also has a waiting list, ordered by when each member joined.
    When places free up they go to the members at the front of the list first.
    """

    def __init__(self, client: Redis) -> None:
        self.client = client

    async def enter(
        self, zone: str, member_id: UUID, stay_seconds: int, capacity: int | None = None
    ) -> Entry:
        """Let the member in if there is a place for them, otherwise add them to the
        zone's waiting list and report their position on it (1 = next in)."""
        now = time.time()
        result = int(
            await self.client.eval(
                ENTER_SCRIPT,
                2,
                CacheKey.OCCUPANCY.build(zone),
                CacheKey.VIP_WAITLIST.build(zone),
                now,
                now + stay_seconds,
                str(member_id),
                capacity or 0,
                CacheKey.OCCUPANCY.ttl_seconds,
                VIP_WAITLIST_HOLD_MINUTES * 60,
            )
        )
        if result == 1:
            return Entry(EntryOutcome.ADMITTED)
        if result == 0:
            return Entry(EntryOutcome.ALREADY_INSIDE)
        return Entry(EntryOutcome.WAITLISTED, waitlist_position=-result)

    async def leave(self, zone: str, member_id: UUID) -> None:
        await self.client.zrem(CacheKey.OCCUPANCY.build(zone), str(member_id))

    async def count(self, zone: str) -> int:
        key = CacheKey.OCCUPANCY.build(zone)
        async with self.client.pipeline(transaction=True) as pipeline:
            pipeline.zremrangebyscore(key, "-inf", time.time())
            pipeline.zcard(key)
            _, count = await pipeline.execute()
        return int(count)

    async def waitlist_position(self, zone: str, member_id: UUID) -> int | None:
        """The member's place on the zone's waiting list (1 = next in), or None."""
        key = CacheKey.VIP_WAITLIST.build(zone)
        oldest_kept = time.time() - VIP_WAITLIST_HOLD_MINUTES * 60
        async with self.client.pipeline(transaction=True) as pipeline:
            pipeline.zremrangebyscore(key, "-inf", oldest_kept)
            pipeline.zrank(key, str(member_id))
            _, rank = await pipeline.execute()
        return None if rank is None else int(rank) + 1

    async def leave_waitlist(self, zone: str, member_id: UUID) -> None:
        await self.client.zrem(CacheKey.VIP_WAITLIST.build(zone), str(member_id))


def get_zone_occupancy() -> ZoneOccupancy:
    return ZoneOccupancy(get_redis_client())
