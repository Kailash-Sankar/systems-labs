#!/usr/bin/env python3
"""Print comparison table from latest run JSON per strategy."""

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

DEFAULT_STRATEGIES = ("naive", "jitter", "singleflight", "swr", "xfetch")


def latest_run(
    runs_dir: Path, strategy: str, replicas: int, profile: str = "hot"
) -> Path | None:
    if profile == "bulk-viz":
        pattern = f"{strategy}-bulk-viz-r{replicas}-*.json"
    elif profile == "bulk":
        pattern = f"{strategy}-bulk-r{replicas}-*.json"
    else:
        pattern = f"{strategy}-r{replicas}-*.json"
    matches = sorted(runs_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if matches:
        return matches[0]
    fallback_pattern = (
        f"{strategy}-bulk-viz-*.json"
        if profile == "bulk-viz"
        else f"{strategy}-bulk-*.json"
        if profile == "bulk"
        else f"{strategy}-*.json"
    )
    fallback = [
        p
        for p in sorted(runs_dir.glob(fallback_pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if profile == "hot"
        or (profile == "bulk-viz") == ("-bulk-viz-" in p.name)
        or (profile == "bulk") == ("-bulk-" in p.name and "-bulk-viz-" not in p.name)
    ]
    return fallback[0] if fallback else None


def load_summary(path: Path) -> dict:
    with path.open() as handle:
        data = json.load(handle)
    summary = data["summary"]
    summary["_file"] = path.name
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare latest stampede runs")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"))
    parser.add_argument("--replicas", type=int, default=3)
    parser.add_argument(
        "--profile",
        choices=("hot", "bulk", "bulk-viz"),
        default="hot",
        help="Match run JSON filename profile (hot vs bulk)",
    )
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help="Comma-separated strategy names",
    )
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    console = Console()
    table = Table(title=f"Strategy comparison ({args.profile}, r{args.replicas}, latest runs)")
    table.add_column("Strategy")
    table.add_column("max DB/s")
    table.add_column("total DB")
    table.add_column("p99 ms")
    table.add_column("hit rate")
    table.add_column("run file")

    missing: list[str] = []
    for strategy in strategies:
        path = latest_run(args.runs_dir, strategy, args.replicas, args.profile)
        if path is None:
            missing.append(strategy)
            continue
        s = load_summary(path)
        table.add_row(
            strategy,
            str(s.get("max_db_queries_in_1s", "?")),
            str(s.get("db_queries_total", "?")),
            f"{s.get('latency_p99_ms', 0):.0f}",
            f"{s.get('cache_hit_rate_pct', 0):.1f}%",
            s["_file"],
        )

    console.print(table)

    if missing:
        console.print(
            f"[yellow]Missing runs for: {', '.join(missing)} — "
            f"run: make up REPLICAS={args.replicas} STRATEGY=<name> && "
            f"make stampede REPLICAS={args.replicas} STRATEGY=<name>[/yellow]"
        )


if __name__ == "__main__":
    main()
