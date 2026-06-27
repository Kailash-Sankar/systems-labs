import asyncio
import time

from redis.asyncio import Redis

from cache_stampede.cache.base import CachedItem, CacheStatus, cache_key
from cache_stampede.config import Settings
from cache_stampede.db import OriginDB
from cache_stampede.metrics import QueryStats


class CacheLockTimeoutError(Exception):
    """Raised when wait/retry exhausts before cache is repopulated."""


def lock_key(item_id: int) -> str:
    return f"lock:{cache_key(item_id)}"


async def _load_and_cache(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    key: str,
    item_id: int,
    ttl_sec: int,
) -> tuple[CachedItem, CacheStatus]:
    await query_stats.record_query()
    record = await asyncio.to_thread(db.get_item, item_id)
    item = CachedItem(id=record.id, name=record.name, payload=record.payload)
    await redis.setex(key, ttl_sec, item.to_json())
    return item, "miss"


async def fetch(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    settings: Settings,
    item_id: int,
) -> tuple[CachedItem, CacheStatus]:
    """Distributed single-flight: one refresher per key, losers wait/retry."""
    key = cache_key(item_id)
    cached = await redis.get(key)
    if cached is not None:
        return CachedItem.from_json(cached), "hit"

    lock = lock_key(item_id)
    acquired = await redis.set(lock, settings.instance_id, nx=True, ex=settings.lock_ttl_sec)

    if acquired:
        try:
            cached = await redis.get(key)
            if cached is not None:
                return CachedItem.from_json(cached), "hit"

            return await _load_and_cache(
                redis,
                db,
                query_stats,
                key,
                item_id,
                settings.cache_ttl_sec,
            )
        finally:
            await redis.delete(lock)

    await query_stats.record_lock_wait()
    deadline = time.monotonic() + (settings.lock_wait_timeout_ms / 1000.0)

    while time.monotonic() < deadline:
        await asyncio.sleep(settings.lock_retry_backoff_ms / 1000.0)
        cached = await redis.get(key)
        if cached is not None:
            return CachedItem.from_json(cached), "wait_hit"

    await query_stats.record_lock_timeout()
    raise CacheLockTimeoutError(f"timed out waiting for cache key {key}")
