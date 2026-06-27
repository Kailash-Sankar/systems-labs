import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from redis.asyncio import Redis

from cache_stampede.cache.registry import get_strategy
from cache_stampede.cache.singleflight import CacheLockTimeoutError
from cache_stampede.config import Settings, get_settings
from cache_stampede.db import OriginDB, ensure_db_exists
from cache_stampede.metrics import QueryStats


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ensure_db_exists(settings.db_path)

    app.state.settings = settings
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.db = OriginDB(settings.db_path, settings.db_sleep_ms)
    app.state.query_stats = QueryStats(app.state.redis)

    yield

    await app.state.redis.aclose()


app = FastAPI(title="cache-stampede", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    settings: Settings = app.state.settings
    return {
        "status": "ok",
        "instance": settings.instance_id,
        "strategy": settings.cache_strategy,
    }


@app.get("/item/{item_id}")
async def get_item(item_id: int) -> dict[str, object]:
    settings: Settings = app.state.settings
    strategy = get_strategy(settings.cache_strategy)

    try:
        item, cache_status = await strategy(
            app.state.redis,
            app.state.db,
            app.state.query_stats,
            settings,
            item_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CacheLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "id": item.id,
        "name": item.name,
        "payload": item.payload,
        "cache": cache_status,
        "instance": settings.instance_id,
    }


@app.get("/stats")
async def stats() -> dict[str, int]:
    query_stats: QueryStats = app.state.query_stats
    return await query_stats.summary()


@app.post("/stats/reset")
async def reset_stats() -> dict[str, str]:
    query_stats: QueryStats = app.state.query_stats
    await query_stats.reset()
    return {"status": "reset"}


@app.post("/admin/flush-cache")
async def flush_cache() -> dict[str, str]:
    redis: Redis = app.state.redis
    await redis.flushdb()
    return {"status": "flushed"}


@app.post("/admin/warm-cache")
async def warm_cache(
    count: int = Query(default=100, ge=1, le=1000),
) -> dict[str, int | str]:
    """Populate items 1..count in one burst — simulates deploy cache warm."""
    settings: Settings = app.state.settings
    strategy = get_strategy(settings.cache_strategy)

    async def warm_one(item_id: int) -> None:
        try:
            await strategy(
                app.state.redis,
                app.state.db,
                app.state.query_stats,
                settings,
                item_id,
            )
        except KeyError:
            pass

    await asyncio.gather(*(warm_one(item_id) for item_id in range(1, count + 1)))
    return {"status": "warmed", "count": count}
