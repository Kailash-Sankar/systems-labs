from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from cache_stampede.cache import jitter, naive, singleflight, swr, xfetch
from cache_stampede.cache.base import CachedItem, CacheStatus
from cache_stampede.config import Settings
from cache_stampede.db import OriginDB
from cache_stampede.metrics import QueryStats

FetchFn = Callable[
    [Redis, OriginDB, QueryStats, Settings, int],
    Awaitable[tuple[CachedItem, CacheStatus]],
]

STRATEGIES: dict[str, FetchFn] = {
    "naive": naive.fetch,
    "jitter": jitter.fetch,
    "singleflight": singleflight.fetch,
    "swr": swr.fetch,
    "xfetch": xfetch.fetch,
}


def get_strategy(name: str) -> FetchFn:
    try:
        return STRATEGIES[name]
    except KeyError as exc:
        known = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"Unknown CACHE_STRATEGY={name!r}. Known: {known}") from exc
