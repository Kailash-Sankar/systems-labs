import asyncio

from redis.asyncio import Redis

from cache_stampede.cache.base import CachedItem, CacheStatus, cache_key
from cache_stampede.config import Settings
from cache_stampede.db import OriginDB
from cache_stampede.metrics import QueryStats


async def fetch(
    redis: Redis,
    db: OriginDB,
    query_stats: QueryStats,
    settings: Settings,
    item_id: int,
) -> tuple[CachedItem, CacheStatus]:
    """Cache-aside: GET on miss → slow DB read → SETEX."""
    key = cache_key(item_id)
    cached = await redis.get(key)
    if cached is not None:
        return CachedItem.from_json(cached), "hit"

    await query_stats.record_query()
    record = await asyncio.to_thread(db.get_item, item_id)
    item = CachedItem(id=record.id, name=record.name, payload=record.payload)
    await redis.setex(key, settings.cache_ttl_sec, item.to_json())
    return item, "miss"
