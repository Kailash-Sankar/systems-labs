import time
import uuid

from redis.asyncio import Redis

STATS_TOTAL_KEY = "stats:db_queries_total"
STATS_TIMES_KEY = "stats:db_query_times"
LOCK_WAITS_KEY = "stats:lock_waits"
LOCK_TIMEOUTS_KEY = "stats:lock_timeouts"


def max_queries_in_one_second(timestamps: list[float]) -> int:
    if not timestamps:
        return 0

    sorted_times = sorted(timestamps)
    max_count = 0
    for start in sorted_times:
        count = sum(1 for t in sorted_times if start <= t < start + 1.0)
        max_count = max(max_count, count)
    return max_count


class QueryStats:
    """Redis-backed counters — shared across app replicas."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def record_query(self) -> None:
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"
        pipe = self._redis.pipeline()
        pipe.incr(STATS_TOTAL_KEY)
        pipe.zadd(STATS_TIMES_KEY, {member: now})
        await pipe.execute()

    async def record_lock_wait(self) -> None:
        await self._redis.incr(LOCK_WAITS_KEY)

    async def record_lock_timeout(self) -> None:
        await self._redis.incr(LOCK_TIMEOUTS_KEY)

    async def reset(self) -> None:
        await self._redis.delete(
            STATS_TOTAL_KEY,
            STATS_TIMES_KEY,
            LOCK_WAITS_KEY,
            LOCK_TIMEOUTS_KEY,
        )

    async def summary(self) -> dict[str, int]:
        total_raw = await self._redis.get(STATS_TOTAL_KEY)
        total = int(total_raw) if total_raw else 0

        lock_waits_raw = await self._redis.get(LOCK_WAITS_KEY)
        lock_waits = int(lock_waits_raw) if lock_waits_raw else 0

        lock_timeouts_raw = await self._redis.get(LOCK_TIMEOUTS_KEY)
        lock_timeouts = int(lock_timeouts_raw) if lock_timeouts_raw else 0

        cutoff = time.time() - 120
        entries = await self._redis.zrangebyscore(
            STATS_TIMES_KEY,
            cutoff,
            "+inf",
            withscores=True,
        )
        times = [score for _, score in entries]

        return {
            "db_queries_total": total,
            "max_db_queries_in_1s": max_queries_in_one_second(times),
            "lock_waits": lock_waits,
            "lock_timeouts": lock_timeouts,
        }
