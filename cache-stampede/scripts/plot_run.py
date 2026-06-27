#!/usr/bin/env python3
"""Render a cache stampede run JSON as a teaching chart."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def load_run(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def plot_run(run: dict, output: Path) -> None:
    seconds = run["timeseries"]["seconds"]
    db_qps = run["timeseries"]["db_queries_per_sec"]
    latency_ms = run["timeseries"]["avg_latency_ms_per_sec"]
    ttl = run.get("cache_ttl_sec", 5)

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.suptitle(
        f"Cache stampede — {run['strategy']}, {run.get('replicas', 1)} replica(s)  "
        f"(max DB/s: {run['summary']['max_db_queries_in_1s']})",
        fontsize=13,
    )

    axes[0].bar(seconds, db_qps, width=0.85, color="#c0392b", alpha=0.85)
    axes[0].set_ylabel("DB queries / sec")
    axes[0].set_ylim(bottom=0)
    axes[0].grid(axis="y", alpha=0.3)
    axes[0].set_title("Origin load — spikes at cache expiry")

    axes[1].plot(seconds, latency_ms, color="#2980b9", linewidth=2, marker="o", markersize=3)
    axes[1].set_ylabel("Avg latency (ms)")
    axes[1].set_xlabel("Seconds into test")
    axes[1].set_ylim(bottom=0)
    axes[1].grid(axis="y", alpha=0.3)
    axes[1].set_title("User-visible latency — pain aligns with DB spikes")

    duration = run["duration_sec"]
    for t in range(ttl, duration + 1, ttl):
        for axis in axes:
            axis.axvline(t, color="#7f8c8d", linestyle="--", linewidth=0.8, alpha=0.6)

    fig.text(
        0.99,
        0.01,
        f"hit rate {run['summary']['cache_hit_rate_pct']:.1f}%  |  "
        f"total DB queries {run['summary']['db_queries_total']}  |  "
        f"dashed lines ≈ TTL ({ttl}s)",
        ha="right",
        va="bottom",
        fontsize=9,
        color="#555555",
    )

    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=140)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a stampede run JSON")
    parser.add_argument("run_file", type=Path, help="Path to run JSON from loadgen")
    parser.add_argument(
        "--output",
        type=Path,
        help="PNG output path (default: same name with .png)",
    )
    args = parser.parse_args()

    output = args.output or args.run_file.with_suffix(".png")
    run = load_run(args.run_file)
    plot_run(run, output)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
