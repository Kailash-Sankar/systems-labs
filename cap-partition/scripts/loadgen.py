#!/usr/bin/env python3
"""Concurrent load generator for CAP partition experiments."""

import argparse
import asyncio
import json
import random
import statistics
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

PARTITION_START_SEC = 20
PARTITION_END_SEC = 35
PARTITION_SCRIPT = Path(__file__).resolve().parent / "partition.sh"


@dataclass
class SecondBucket:
    requests: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    min_score: int | None = None
    max_score: int | None = None


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


def parse_urls(raw: str) -> list[str]:
    urls = [part.strip().rstrip("/") for part in raw.split(",") if part.strip()]
    if not urls:
        raise ValueError("At least one URL is required")
    return urls


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def observe_score(bucket: SecondBucket, score: int) -> None:
    if bucket.min_score is None or score < bucket.min_score:
        bucket.min_score = score
    if bucket.max_score is None or score > bucket.max_score:
        bucket.max_score = score


def node_from_url(url: str) -> str:
    port = url.rsplit(":", 1)[-1]
    return {"8001": "node1", "8002": "node2", "8003": "node3"}.get(port, url)


def run_partition(action: str) -> None:
    subprocess.run(
        ["bash", str(PARTITION_SCRIPT), action],
        check=True,
        capture_output=True,
        text=True,
    )


async def fetch_node_scores(
    client: httpx.AsyncClient,
    urls: list[str],
) -> dict[str, int]:
    scores: dict[str, int] = {}
    for url in urls:
        try:
            response = await client.get(f"{url}/internal/score")
            response.raise_for_status()
            scores[node_from_url(url)] = int(response.json()["score"])
        except httpx.HTTPError:
            continue
    return scores


def score_spread(scores: dict[str, int]) -> int:
    if len(scores) < 2:
        return 0
    values = list(scores.values())
    return max(values) - min(values)


async def trigger_merge_on_all_nodes(
    client: httpx.AsyncClient,
    urls: list[str],
) -> None:
    await asyncio.gather(
        *(client.post(f"{url}/admin/merge") for url in urls),
        return_exceptions=True,
    )


async def trigger_sync_on_all_nodes(
    client: httpx.AsyncClient,
    urls: list[str],
) -> None:
    await asyncio.gather(
        *(client.post(f"{url}/admin/sync") for url in urls),
        return_exceptions=True,
    )


async def orchestrate_partition(
    enabled: bool,
    started_at: float,
    stop_at: float,
    console: Console,
    heal_event: asyncio.Event,
) -> None:
    if not enabled:
        return

    partitioned = False
    healed = False
    try:
        while time.monotonic() < stop_at:
            elapsed = time.monotonic() - started_at
            if not partitioned and elapsed >= PARTITION_START_SEC:
                await asyncio.to_thread(run_partition, "on")
                console.print(
                    f"[red]Partition ON[/red] at t={PARTITION_START_SEC}s "
                    "(node3 isolated from node1+node2)"
                )
                partitioned = True
            if partitioned and not healed and elapsed >= PARTITION_END_SEC:
                await asyncio.to_thread(run_partition, "off")
                console.print(f"[green]Partition OFF[/green] at t={PARTITION_END_SEC}s")
                heal_event.set()
                healed = True
            await asyncio.sleep(0.25)
    finally:
        if partitioned and not healed:
            await asyncio.to_thread(run_partition, "off")
            heal_event.set()
            console.print("[green]Partition OFF[/green] (cleanup after load test)")


def bucket_spread(bucket: SecondBucket) -> int:
    if bucket.min_score is None or bucket.max_score is None:
        return 0
    return bucket.max_score - bucket.min_score


async def fetch_cluster_max_score(client: httpx.AsyncClient, urls: list[str]) -> int | None:
    scores: list[int] = []
    for url in urls:
        try:
            response = await client.get(f"{url}/internal/score")
            response.raise_for_status()
            scores.append(int(response.json()["score"]))
        except httpx.HTTPError:
            continue
    return max(scores) if scores else None


async def worker(
    round_robin: UrlRoundRobin,
    all_urls: list[str],
    buckets: dict[int, SecondBucket],
    instance_counts: Counter[str],
    write_latencies_ms: list[float],
    stale_read_count: list[int],
    partition_errors_by_node: Counter[str],
    started_at: float,
    stop_at: float,
) -> tuple[int, int, int]:
    reads = 0
    writes = 0
    errors = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        while time.monotonic() < stop_at:
            base_url = await round_robin.next()
            is_read = random.random() < 0.5
            second = int(time.monotonic() - started_at)
            bucket = buckets.setdefault(second, SecondBucket())
            started = time.perf_counter()

            try:
                if is_read:
                    response = await client.get(f"{base_url}/score")
                else:
                    response = await client.post(f"{base_url}/score/increment")
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPError:
                bucket.requests += 1
                bucket.errors += 1
                errors += 1
                if PARTITION_START_SEC <= second < PARTITION_END_SEC:
                    partition_errors_by_node[node_from_url(base_url)] += 1
                await asyncio.sleep(0.05)
                continue

            elapsed_ms = (time.perf_counter() - started) * 1000
            score = int(body["score"])
            bucket.requests += 1
            bucket.latencies_ms.append(elapsed_ms)
            observe_score(bucket, score)
            instance_counts[body.get("node", "unknown")] += 1

            if is_read:
                reads += 1
                cluster_max = await fetch_cluster_max_score(client, all_urls)
                if cluster_max is not None and score < cluster_max:
                    stale_read_count[0] += 1
            else:
                writes += 1
                write_latencies_ms.append(elapsed_ms)

            await asyncio.sleep(0.05)

    return reads, writes, errors


async def wait_for_nodes(client: httpx.AsyncClient, urls: list[str]) -> None:
    for _ in range(30):
        try:
            for url in urls:
                response = await client.get(f"{url}/health")
                response.raise_for_status()
            return
        except httpx.HTTPError:
            await asyncio.sleep(1)
    raise RuntimeError(f"Nodes not healthy after 30s: {urls}")


async def sample_spread(
    client: httpx.AsyncClient,
    urls: list[str],
    spread_timeline: list[tuple[float, int]],
    started_at: float,
    stop_at: float,
) -> None:
    """Poll all nodes periodically; track max concurrent value spread."""
    while time.monotonic() < stop_at:
        scores: list[int] = []
        for url in urls:
            try:
                response = await client.get(f"{url}/internal/score")
                response.raise_for_status()
                scores.append(int(response.json()["score"]))
            except httpx.HTTPError:
                continue
        elapsed = time.monotonic() - started_at
        if len(scores) >= 2:
            spread_timeline.append((elapsed, max(scores) - min(scores)))
        elif len(scores) == 1:
            spread_timeline.append((elapsed, 0))
        await asyncio.sleep(0.2)


def spread_per_second(
    duration_sec: int,
    spread_timeline: list[tuple[float, int]],
) -> list[int]:
    per_sec = [0] * duration_sec
    for elapsed, spread in spread_timeline:
        second = min(int(elapsed), duration_sec - 1)
        per_sec[second] = max(per_sec[second], spread)
    return per_sec


def max_spread_in_window(
    spread_timeline: list[tuple[float, int]],
    start_sec: float,
    end_sec: float,
) -> int:
    window = [spread for elapsed, spread in spread_timeline if start_sec <= elapsed < end_sec]
    return max(window) if window else 0


def max_spread_after(
    spread_timeline: list[tuple[float, int]],
    after_sec: float,
) -> int:
    window = [spread for elapsed, spread in spread_timeline if elapsed >= after_sec]
    return max(window) if window else 0


async def monitor_convergence(
    client: httpx.AsyncClient,
    urls: list[str],
    heal_event: asyncio.Event,
    started_at: float,
    stop_at: float,
    replication: str,
    merge_on_heal: bool,
    console: Console,
) -> dict[str, float | int | dict[str, int] | None]:
    """Track spread at heal and time until all nodes agree."""
    result: dict[str, float | int | dict[str, int] | None] = {
        "convergence_seconds": None,
        "spread_at_heal": None,
        "node_scores_at_heal": None,
        "merged_score": None,
        "divergent_increments_at_heal": None,
    }

    if not merge_on_heal:
        return result

    try:
        await asyncio.wait_for(heal_event.wait(), timeout=stop_at - time.monotonic())
    except TimeoutError:
        return result

    heal_at = time.monotonic()
    scores_at_heal = await fetch_node_scores(client, urls)
    spread_at_heal = score_spread(scores_at_heal)
    result["spread_at_heal"] = spread_at_heal
    result["node_scores_at_heal"] = scores_at_heal
    if scores_at_heal:
        values = list(scores_at_heal.values())
        result["divergent_increments_at_heal"] = max(values) - min(values)

    if replication in ("ap", "async"):
        console.print("[yellow]LWW merge[/yellow] triggered on all nodes at heal")
        await trigger_merge_on_all_nodes(client, urls)
    elif replication == "sync":
        console.print("[yellow]Catch-up sync[/yellow] triggered on all nodes at heal")
        await trigger_sync_on_all_nodes(client, urls)

    converged_at: float | None = None
    while time.monotonic() < stop_at:
        scores = await fetch_node_scores(client, urls)
        if len(scores) >= len(urls) and score_spread(scores) == 0:
            if converged_at is None:
                converged_at = time.monotonic()
                result["convergence_seconds"] = converged_at - heal_at
                result["merged_score"] = next(iter(scores.values()))
                console.print(
                    f"[green]Converged[/green] at t={converged_at - started_at:.1f}s "
                    f"(+{result['convergence_seconds']:.2f}s after heal)"
                )
            break
        await asyncio.sleep(0.2)

    if converged_at is None and scores_at_heal:
        result["merged_score"] = max(scores_at_heal.values())
    return result


async def run_load_test(
    urls: list[str],
    duration_sec: int,
    concurrency: int,
    replication: str,
    nodes: int,
    partition: bool,
    merge_on_heal: bool,
    output: Path,
) -> None:
    console = Console()
    primary = urls[0]
    round_robin = UrlRoundRobin(urls)
    convergence: dict[str, float | int | dict[str, int] | None] = {}
    node_scores_at_end: dict[str, int] = {}
    final_score = -1

    if partition:
        await asyncio.to_thread(run_partition, "off")

    async with httpx.AsyncClient(timeout=10.0) as admin_client:
        await wait_for_nodes(admin_client, urls)
        for url in urls:
            await admin_client.post(f"{url}/admin/reset")

        buckets: dict[int, SecondBucket] = {}
        instance_counts: Counter[str] = Counter()
        write_latencies_ms: list[float] = []
        stale_read_count = [0]
        partition_errors_by_node: Counter[str] = Counter()
        heal_event = asyncio.Event()
        started_at = time.monotonic()
        stop_at = started_at + duration_sec

        workers = [
            asyncio.create_task(
                worker(
                    round_robin,
                    urls,
                    buckets,
                    instance_counts,
                    write_latencies_ms,
                    stale_read_count,
                    partition_errors_by_node,
                    started_at,
                    stop_at,
                )
            )
            for _ in range(concurrency)
        ]
        spread_timeline: list[tuple[float, int]] = []
        sampler = asyncio.create_task(
            sample_spread(admin_client, urls, spread_timeline, started_at, stop_at)
        )
        partition_task = asyncio.create_task(
            orchestrate_partition(partition, started_at, stop_at, console, heal_event)
        )
        convergence_task = asyncio.create_task(
            monitor_convergence(
                admin_client,
                urls,
                heal_event,
                started_at,
                stop_at,
                replication,
                merge_on_heal and partition,
                console,
            )
        )
        worker_results = await asyncio.gather(*workers)
        await sampler
        await partition_task
        convergence = await convergence_task
        total_reads = sum(r for r, _, _ in worker_results)
        total_writes = sum(w for _, w, _ in worker_results)
        total_errors = sum(e for _, _, e in worker_results)

        try:
            final_response = await admin_client.get(f"{primary}/score")
            final_response.raise_for_status()
            final_score = int(final_response.json()["score"])
        except httpx.HTTPError:
            final_score = -1

        node_scores_at_end = await fetch_node_scores(admin_client, urls)

    all_latencies = [
        latency for bucket in buckets.values() for latency in bucket.latencies_ms
    ]
    write_latencies = write_latencies_ms

    global_min = min(
        (bucket.min_score for bucket in buckets.values() if bucket.min_score is not None),
        default=None,
    )
    global_max = max(
        (bucket.max_score for bucket in buckets.values() if bucket.max_score is not None),
        default=None,
    )
    spread_values = [spread for _, spread in spread_timeline]
    max_value_spread = max(spread_values) if spread_values else 0

    errors_during_partition = sum(
        bucket.errors
        for second, bucket in buckets.items()
        if PARTITION_START_SEC <= second < PARTITION_END_SEC
    )
    max_spread_during_partition = max_spread_in_window(
        spread_timeline,
        PARTITION_START_SEC,
        PARTITION_END_SEC,
    )
    max_spread_after_heal = max_spread_after(spread_timeline, PARTITION_END_SEC)
    latencies_during_partition = [
        latency
        for second, bucket in buckets.items()
        if PARTITION_START_SEC <= second < PARTITION_END_SEC
        for latency in bucket.latencies_ms
    ]
    p99_during_partition_ms = percentile(latencies_during_partition, 99)

    summary = {
        "urls": urls,
        "nodes": nodes,
        "replication": replication,
        "duration_sec": duration_sec,
        "concurrency": concurrency,
        "partition_enabled": partition,
        "merge_on_heal": merge_on_heal and partition,
        "reads_total": total_reads,
        "writes_total": total_writes,
        "increments_total": total_writes,
        "errors_total": total_errors,
        "errors_during_partition": errors_during_partition,
        "errors_during_partition_by_node": dict(sorted(partition_errors_by_node.items())),
        "final_score": final_score,
        "max_value_spread": max_value_spread,
        "max_value_spread_during_partition": max_spread_during_partition,
        "max_value_spread_after_heal": max_spread_after_heal,
        "p99_during_partition_ms": p99_during_partition_ms,
        "convergence_seconds": convergence.get("convergence_seconds"),
        "spread_at_heal": convergence.get("spread_at_heal"),
        "node_scores_at_heal": convergence.get("node_scores_at_heal"),
        "node_scores_at_end": node_scores_at_end,
        "merged_score": convergence.get("merged_score"),
        "divergent_increments_at_heal": convergence.get("divergent_increments_at_heal"),
        "min_score_seen": global_min,
        "max_score_seen": global_max,
        "latency_p50_ms": percentile(all_latencies, 50),
        "latency_p99_ms": percentile(all_latencies, 99),
        "latency_mean_ms": statistics.mean(all_latencies) if all_latencies else 0.0,
        "p99_write_ms": percentile(write_latencies, 99),
        "stale_read_count": stale_read_count[0],
        "requests_by_node": dict(sorted(instance_counts.items())),
    }

    table = Table(title="CAP Partition Load Test")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("URLs", ", ".join(urls))
    table.add_row("Nodes", str(nodes))
    table.add_row("Replication", replication)
    table.add_row("Duration (s)", str(duration_sec))
    table.add_row("Concurrency", str(concurrency))
    if partition:
        table.add_row(
            "Partition window",
            f"t={PARTITION_START_SEC}s → t={PARTITION_END_SEC}s (node3 isolated)",
        )
    table.add_row("Reads", str(total_reads))
    table.add_row("Increments", str(total_writes))
    table.add_row("Errors", str(total_errors))
    table.add_row("Errors during partition", str(errors_during_partition))
    for node, count in sorted(partition_errors_by_node.items()):
        table.add_row(f"  partition errors @ {node}", str(count))
    table.add_row("Final score", str(final_score))
    table.add_row("Max value spread", str(max_value_spread))
    table.add_row("Spread during partition", str(max_spread_during_partition))
    if merge_on_heal and partition:
        table.add_row("Spread at heal", str(summary.get("spread_at_heal", "n/a")))
        table.add_row("Convergence after heal (s)", str(summary.get("convergence_seconds", "n/a")))
        table.add_row("Max spread after heal", str(max_spread_after_heal))
        if summary.get("node_scores_at_heal"):
            table.add_row("Scores at heal", str(summary["node_scores_at_heal"]))
        if summary.get("node_scores_at_end"):
            table.add_row("Scores at end", str(summary["node_scores_at_end"]))
    table.add_row("Stale reads", str(summary["stale_read_count"]))
    for node, count in sorted(instance_counts.items()):
        table.add_row(f"  via {node}", str(count))
    table.add_row("Latency p50 (ms)", f"{summary['latency_p50_ms']:.1f}")
    table.add_row("Latency p99 (ms)", f"{summary['latency_p99_ms']:.1f}")
    table.add_row("p99 write (ms)", f"{summary['p99_write_ms']:.1f}")
    console.print(table)

    payload = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "replication": replication,
        "nodes": nodes,
        "urls": urls,
        "duration_sec": duration_sec,
        "concurrency": concurrency,
        "partition": {
            "enabled": partition,
            "start_sec": PARTITION_START_SEC,
            "end_sec": PARTITION_END_SEC,
        },
        "summary": summary,
        "timeseries": {
            "seconds": list(range(duration_sec)),
            "requests_per_sec": [
                buckets.get(second, SecondBucket()).requests for second in range(duration_sec)
            ],
            "errors_per_sec": [
                buckets.get(second, SecondBucket()).errors for second in range(duration_sec)
            ],
            "spread_per_sec": spread_per_second(duration_sec, spread_timeline),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2))
    console.print(f"[dim]Run data → {output}[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CAP partition load test")
    parser.add_argument(
        "--urls",
        default="http://localhost:8001",
        help="Comma-separated node base URLs (round-robin)",
    )
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--replication", default="single")
    parser.add_argument("--nodes", type=int, default=1)
    parser.add_argument("--partition", type=int, choices=(0, 1), default=0)
    parser.add_argument(
        "--merge-on-heal",
        type=int,
        choices=(0, 1),
        default=1,
        help="Trigger LWW merge at partition heal (Phase 5)",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    asyncio.run(
        run_load_test(
            urls=parse_urls(args.urls),
            duration_sec=args.duration,
            concurrency=args.concurrency,
            replication=args.replication,
            nodes=args.nodes,
            partition=bool(args.partition),
            merge_on_heal=bool(args.merge_on_heal),
            output=args.output,
        )
    )


if __name__ == "__main__":
    main()
