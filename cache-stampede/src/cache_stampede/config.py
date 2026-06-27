import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    redis_url: str
    db_path: str
    cache_ttl_sec: int
    db_sleep_ms: int
    cache_strategy: str
    instance_id: str
    lock_ttl_sec: int
    lock_wait_timeout_ms: int
    lock_retry_backoff_ms: int
    swr_stale_sec: int
    xfetch_beta: float
    ttl_jitter_pct: int


def get_settings() -> Settings:
    return Settings(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        db_path=os.getenv("DB_PATH", "data/app.db"),
        cache_ttl_sec=int(os.getenv("CACHE_TTL_SEC", "5")),
        db_sleep_ms=int(os.getenv("DB_SLEEP_MS", "200")),
        cache_strategy=os.getenv("CACHE_STRATEGY", "naive"),
        instance_id=os.getenv("INSTANCE_ID", "app1"),
        lock_ttl_sec=int(os.getenv("LOCK_TTL_SEC", "10")),
        lock_wait_timeout_ms=int(os.getenv("LOCK_WAIT_TIMEOUT_MS", "5000")),
        lock_retry_backoff_ms=int(os.getenv("LOCK_RETRY_BACKOFF_MS", "50")),
        swr_stale_sec=int(os.getenv("SWR_STALE_SEC", "5")),
        xfetch_beta=float(os.getenv("XFETCH_BETA", "1.0")),
        ttl_jitter_pct=int(os.getenv("TTL_JITTER_PCT", "20")),
    )
