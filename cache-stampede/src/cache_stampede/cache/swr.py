import asyncio
import time

from redis.asyncio import Redis

from cache_stampede.cache.base import CachedItem, CacheStatus, cache_key
from cache_stampede.cache.envelope import CacheEnvelope
from cache_stampede.cache.singleflight import CacheLockTimeoutError, lock_key
from cache_stampede.config import Settings
from cache_stampede.db import OriginDB
from cache_stampede.metrics import QueryStats


def hard_ttl_sec(settings: Settings) -> int:
    return settings.cache_ttl_sec + settings.swr_stale_sec


async def _fetch_and_store(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    key: str,
    item_id: int,
    settings: Settings,
) -> CachedItem:
    await query_stats.record_query()
    record = await asyncio.to_thread(db.get_item, item_id)
    item = CachedItem(id=record.id, name=record.name, payload=record.payload)
    envelope = CacheEnvelope(item=item, cached_at=time.time())
    await redis.setex(key, hard_ttl_sec(settings), envelope.to_json())
    return item


async def _try_background_refresh(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    settings: Settings,
    item_id: int,
    key: str,
) -> None:
    lock = lock_key(item_id)
    acquired = await redis.set(lock, settings.instance_id, nx=True, ex=settings.lock_ttl_sec)
    if not acquired:
        return

    try:
        raw = await redis.get(key)
        if raw is not None:
            envelope = CacheEnvelope.from_json(raw)
            if envelope.age_sec() < settings.cache_ttl_sec:
                return

        await _fetch_and_store(redis, db, query_stats, key, item_id, settings)
    finally:
        await redis.delete(lock)


async def _blocking_refresh(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    settings: Settings,
    item_id: int,
    key: str,
) -> tuple[CachedItem, CacheStatus]:
    """True miss or past hard stale window — same coordination as single-flight."""
    lock = lock_key(item_id)
    acquired = await redis.set(lock, settings.instance_id, nx=True, ex=settings.lock_ttl_sec)

    if acquired:
        try:
            raw = await redis.get(key)
            if raw is not None:
                envelope = CacheEnvelope.from_json(raw)
                if envelope.age_sec() < settings.cache_ttl_sec + settings.swr_stale_sec:
                    status: CacheStatus = (
                        "hit" if envelope.age_sec() < settings.cache_ttl_sec else "stale"
                    )
                    return envelope.item, status

            item = await _fetch_and_store(
                redis, db, query_stats, key, item_id, settings
            )
            return item, "miss"
        finally:
            await redis.delete(lock)

    await query_stats.record_lock_wait()
    deadline = time.monotonic() + (settings.lock_wait_timeout_ms / 1000.0)

    while time.monotonic() < deadline:
        await asyncio.sleep(settings.lock_retry_backoff_ms / 1000.0)
        raw = await redis.get(key)
        if raw is not None:
            envelope = CacheEnvelope.from_json(raw)
            status = "wait_hit" if envelope.age_sec() < settings.cache_ttl_sec else "stale"
            return envelope.item, status

    await query_stats.record_lock_timeout()
    raise CacheLockTimeoutError(f"timed out waiting for cache key {key}")


async def fetch(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    settings: Settings,
    item_id: int,
) -> tuple[CachedItem, CacheStatus]:
    """Stale-while-revalidate: serve stale after soft TTL; refresh in background."""
    key = cache_key(item_id)
    raw = await redis.get(key)

    if raw is None:
        return await _blocking_refresh(
            redis, db, query_stats, settings, item_id, key
        )

    envelope = CacheEnvelope.from_json(raw)
    age = envelope.age_sec()
    soft = settings.cache_ttl_sec
    hard = soft + settings.swr_stale_sec

    if age < soft:
        return envelope.item, "hit"

    if age < hard:
        asyncio.create_task(
            _try_background_refresh(
                redis, db, query_stats, settings, item_id, key
            )
        )
        return envelope.item, "stale"

    return await _blocking_refresh(
        redis, db, query_stats, settings, item_id, key
    )
