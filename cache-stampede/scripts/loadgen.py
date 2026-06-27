#!/usr/bin/env python3
"""Concurrent load generator for cache stampede experiments."""

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

HOT_ITEM_ID = 1
COLD_ITEM_IDS = list(range(2, 11))
HOT_KEY_RATIO = 0.95


def pick_item_id(profile: str, item_count: int) -> int:
    if profile == "bulk":
        return random.randint(1, item_count)
    if random.random() < HOT_KEY_RATIO:
        return HOT_ITEM_ID
    return random.choice(COLD_ITEM_IDS)


def parse_urls(raw: str) -> list[str]:
    urls = [part.strip().rstrip("/") for part in raw.split(",") if part.strip()]
    if not urls:
        raise ValueError("At least one URL is required")
    return urls


@dataclass
class SecondBucket:
    latencies_ms: list[float] = field(default_factory=list)
    cache_hits: int = 0
    wait_hits: int = 0
    stale_hits: int = 0
    early_refresh_hits: int = 0
    requests: int = 0


class UrlRoundRobin:
    def __init__(self, urls: list[str]) -> None:
        self._urls = urls
        self._index = 0
        self._lock = asyncio.Lock()

    async def next(self) -> str:
        async with self._lock:
            url = self._urls[self._index % len(self._urls)]
            self._index += 1
            return url


async def worker(
    round_robin: UrlRoundRobin,
    buckets: dict[int, SecondBucket],
    instance_counts: Counter[str],
    started_at: float,
    stop_at: float,
    profile: str,
    item_count: int,
) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        while time.monotonic() < stop_at:
            item_id = pick_item_id(profile, item_count)
            base_url = await round_robin.next()
            started = time.perf_counter()
            second = int(time.monotonic() - started_at)

            try:
                response = await client.get(f"{base_url}/item/{item_id}")
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPError:
                await asyncio.sleep(0.1)
                continue

            elapsed_ms = (time.perf_counter() - started) * 1000
            bucket = buckets.setdefault(second, SecondBucket())
            bucket.requests += 1
            bucket.latencies_ms.append(elapsed_ms)
            instance_counts[body.get("instance", "unknown")] += 1
            cache_status = body.get("cache")
            if cache_status in ("hit", "wait_hit", "stale", "early_refresh"):
                bucket.cache_hits += 1
            if cache_status == "wait_hit":
                bucket.wait_hits += 1
            if cache_status == "stale":
                bucket.stale_hits += 1
            if cache_status == "early_refresh":
                bucket.early_refresh_hits += 1

            await asyncio.sleep(0.1)


async def sample_stats(
    client: httpx.AsyncClient,
    stats_url: str,
    db_queries_per_sec: list[int],
    stop_at: float,
) -> None:
    previous_total = 0
    while time.monotonic() < stop_at:
        await asyncio.sleep(1.0)
        try:
            response = await client.get(f"{stats_url}/stats")
            response.raise_for_status()
            total = response.json()["db_queries_total"]
        except httpx.HTTPError:
            db_queries_per_sec.append(0)
            continue

        db_queries_per_sec.append(max(total - previous_total, 0))
        previous_total = total


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def build_timeseries(
    duration_sec: int,
    buckets: dict[int, SecondBucket],
    db_queries_per_sec: list[int],
) -> dict[str, list[float]]:
    seconds = list(range(duration_sec))
    latency_series: list[float] = []
    for second in seconds:
        bucket = buckets.get(second)
        if bucket and bucket.latencies_ms:
            latency_series.append(statistics.mean(bucket.latencies_ms))
        else:
            latency_series.append(0.0)

    padded_db = db_queries_per_sec[:duration_sec]
    if len(padded_db) < duration_sec:
        padded_db.extend([0] * (duration_sec - len(padded_db)))

    return {
        "seconds": seconds,
        "db_queries_per_sec": padded_db,
        "avg_latency_ms_per_sec": latency_series,
    }


async def wait_for_apps(client: httpx.AsyncClient, urls: list[str]) -> None:
    for attempt in range(20):
        try:
            for url in urls:
                response = await client.get(f"{url}/health")
                response.raise_for_status()
            return
        except httpx.HTTPError:
            await asyncio.sleep(1)
    raise RuntimeError(f"Apps not healthy after 20s: {urls}")


async def run_load_test(
    urls: list[str],
    duration_sec: int,
    concurrency: int,
    flush_cache: bool,
    warm_cache: bool,
    item_count: int,
    profile: str,
    strategy: str,
    replicas: int,
    output: Path | None,
) -> None:
    console = Console()
    primary = urls[0]
    round_robin = UrlRoundRobin(urls)

    async with httpx.AsyncClient(timeout=30.0) as admin_client:
        await wait_for_apps(admin_client, urls)

        await admin_client.post(f"{primary}/stats/reset")
        if flush_cache:
            await admin_client.post(f"{primary}/admin/flush-cache")
        if warm_cache:
            await admin_client.post(
                f"{primary}/admin/warm-cache",
                params={"count": item_count},
            )
            await admin_client.post(f"{primary}/stats/reset")

        buckets: dict[int, SecondBucket] = {}
        instance_counts: Counter[str] = Counter()
        db_queries_per_sec: list[int] = []
        started_at = time.monotonic()
        stop_at = started_at + duration_sec

        sampler = asyncio.create_task(
            sample_stats(admin_client, primary, db_queries_per_sec, stop_at)
        )
        workers = [
            asyncio.create_task(
                worker(
                    round_robin,
                    buckets,
                    instance_counts,
                    started_at,
                    stop_at,
                    profile,
                    item_count,
                )
            )
            for _ in range(concurrency)
        ]
        await asyncio.gather(*workers)
        await sampler

        stats_response = await admin_client.get(f"{primary}/stats")
        stats_response.raise_for_status()
        stats = stats_response.json()

    all_latencies = [
        latency
        for bucket in buckets.values()
        for latency in bucket.latencies_ms
    ]
    total_requests = sum(bucket.requests for bucket in buckets.values())
    hit_count = sum(bucket.cache_hits for bucket in buckets.values())
    wait_hit_count = sum(bucket.wait_hits for bucket in buckets.values())
    stale_hit_count = sum(bucket.stale_hits for bucket in buckets.values())
    early_refresh_count = sum(bucket.early_refresh_hits for bucket in buckets.values())
    timeseries = build_timeseries(duration_sec, buckets, db_queries_per_sec)

    summary = {
        "urls": urls,
        "replicas": replicas,
        "strategy": strategy,
        "profile": profile,
        "item_count": item_count,
        "warm_cache": warm_cache,
        "duration_sec": duration_sec,
        "concurrency": concurrency,
        "requests_completed": total_requests,
        "cache_hits": hit_count,
        "wait_hits": wait_hit_count,
        "stale_hits": stale_hit_count,
        "early_refresh_hits": early_refresh_count,
        "cache_hit_rate_pct": (hit_count / total_requests * 100) if total_requests else 0.0,
        "db_queries_total": stats.get("db_queries_total", 0),
        "max_db_queries_in_1s": stats.get("max_db_queries_in_1s", 0),
        "lock_waits": stats.get("lock_waits", 0),
        "lock_timeouts": stats.get("lock_timeouts", 0),
        "latency_p50_ms": percentile(all_latencies, 50),
        "latency_p99_ms": percentile(all_latencies, 99),
        "latency_mean_ms": statistics.mean(all_latencies) if all_latencies else 0.0,
        "requests_by_instance": dict(sorted(instance_counts.items())),
    }

    table = Table(title="Cache Stampede Load Test")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("URLs", ", ".join(urls))
    table.add_row("Replicas", str(replicas))
    table.add_row("Strategy", strategy)
    table.add_row("Profile", profile)
    if profile == "bulk":
        table.add_row("Item count", str(item_count))
        table.add_row("Cache warmed", "yes" if warm_cache else "no")
    table.add_row("Duration (s)", str(duration_sec))
    table.add_row("Concurrency", str(concurrency))
    table.add_row("Requests completed", str(total_requests))
    for instance, count in sorted(instance_counts.items()):
        table.add_row(f"  via {instance}", str(count))
    table.add_row("Cache hits", str(hit_count))
    if wait_hit_count:
        table.add_row("  wait_hit (coordinated)", str(wait_hit_count))
    if stale_hit_count:
        table.add_row("  stale (SWR)", str(stale_hit_count))
    if early_refresh_count:
        table.add_row("  early_refresh (XFetch)", str(early_refresh_count))
    table.add_row("Cache hit rate", f"{summary['cache_hit_rate_pct']:.1f}%")
    table.add_row("DB queries (total)", str(summary["db_queries_total"]))
    table.add_row("Max DB queries in 1s", str(summary["max_db_queries_in_1s"]))
    if summary.get("lock_waits", 0) or strategy == "singleflight":
        table.add_row("Lock waits", str(summary.get("lock_waits", 0)))
        table.add_row("Lock timeouts", str(summary.get("lock_timeouts", 0)))
    table.add_row("Latency p50 (ms)", f"{summary['latency_p50_ms']:.1f}")
    table.add_row("Latency p99 (ms)", f"{summary['latency_p99_ms']:.1f}")
    table.add_row("Latency mean (ms)", f"{summary['latency_mean_ms']:.1f}")
    console.print(table)

    if output is not None:
        payload = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "strategy": strategy,
            "profile": profile,
            "replicas": replicas,
            "urls": urls,
            "duration_sec": duration_sec,
            "concurrency": concurrency,
            "cache_ttl_sec": 5,
            "summary": summary,
            "timeseries": timeseries,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2))
        console.print(f"[dim]Run data → {output}[/dim]")
        console.print(f"[dim]Chart      → uv run python scripts/plot_run.py {output}[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cache stampede load test")
    parser.add_argument(
        "--urls",
        default="http://localhost:8001",
        help="Comma-separated app base URLs (round-robin)",
    )
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--strategy", default="naive")
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument(
        "--profile",
        choices=("hot", "bulk"),
        default="hot",
        help="hot = 95%% traffic to item:1; bulk = even traffic across items",
    )
    parser.add_argument(
        "--item-count",
        type=int,
        default=100,
        help="Items 1..N for bulk profile (must exist in SQLite)",
    )
    parser.add_argument(
        "--warm-cache",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Warm all items via /admin/warm-cache before load (bulk demo)",
    )
    parser.add_argument(
        "--flush-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Flush Redis before test (cold start)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON time series for plotting",
    )
    args = parser.parse_args()

    urls = parse_urls(args.urls)
    output = args.output
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        profile_suffix = f"-{args.profile}" if args.profile != "hot" else ""
        output = (
            Path("data/runs")
            / f"{args.strategy}{profile_suffix}-r{args.replicas}-{stamp}.json"
        )

    asyncio.run(
        run_load_test(
            urls=urls,
            duration_sec=args.duration,
            concurrency=args.concurrency,
            flush_cache=args.flush_cache,
            warm_cache=args.warm_cache,
            item_count=args.item_count,
            profile=args.profile,
            strategy=args.strategy,
            replicas=args.replicas,
            output=output,
        )
    )


if __name__ == "__main__":
    main()
