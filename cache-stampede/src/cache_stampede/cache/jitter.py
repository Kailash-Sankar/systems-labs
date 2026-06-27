import asyncio
import random

from redis.asyncio import Redis

from cache_stampede.cache.base import CachedItem, CacheStatus, cache_key
from cache_stampede.config import Settings
from cache_stampede.db import OriginDB
from cache_stampede.metrics import QueryStats


def jittered_ttl_sec(settings: Settings) -> int:
    """Add random extra seconds so keys written together don't expire together."""
    pct = settings.ttl_jitter_pct
    if pct <= 0:
        return settings.cache_ttl_sec
    extra = random.randint(0, max(int(settings.cache_ttl_sec * pct / 100), 1))
    return settings.cache_ttl_sec + extra


async def fetch(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    settings: Settings,
    item_id: int,
) -> tuple[CachedItem, CacheStatus]:
    """Naive cache-aside with TTL jitter on SETEX — partial stampede mitigation."""
    key = cache_key(item_id)
    cached = await redis.get(key)
    if cached is not None:
        return CachedItem.from_json(cached), "hit"

    await query_stats.record_query()
    record = await asyncio.to_thread(db.get_item, item_id)
    item = CachedItem(id=record.id, name=record.name, payload=record.payload)
    await redis.setex(key, jittered_ttl_sec(settings), item.to_json())
    return item, "miss"
