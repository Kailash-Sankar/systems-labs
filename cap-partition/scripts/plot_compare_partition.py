#!/usr/bin/env python3
"""Overlay CP vs AP partition runs on one teaching chart."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def load_run(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def latest_partition_run(runs_dir: Path, replication: str, nodes: int) -> Path | None:
    pattern = f"{replication}-n{nodes}-partition-*.json"
    matches = sorted(runs_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def plot_compare(cp_run: dict, ap_run: dict, output: Path) -> None:
    cp_ts = cp_run["timeseries"]
    ap_ts = ap_run["timeseries"]
    seconds = cp_ts["seconds"]
    partition = cp_run.get("partition", {})
    p_start = partition.get("start_sec", 20)
    p_end = partition.get("end_sec", 35)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    cp_summary = cp_run["summary"]
    ap_summary = ap_run["summary"]
    fig.suptitle(
        "CAP under partition — CP (sync) vs AP (local writes), same load script",
        fontsize=13,
        fontweight="bold",
    )

    axes[0].plot(
        seconds,
        cp_ts["errors_per_sec"],
        color="#c0392b",
        linewidth=2,
        label=f"CP sync — {cp_summary.get('errors_during_partition', 0)} errors in window",
    )
    axes[0].plot(
        seconds,
        ap_ts["errors_per_sec"],
        color="#e67e22",
        linewidth=2,
        linestyle="--",
        label=f"AP local — {ap_summary.get('errors_during_partition', 0)} errors in window",
    )
    axes[0].set_ylabel("Errors / sec")
    axes[0].set_ylim(bottom=0)
    axes[0].grid(axis="y", alpha=0.3)
    axes[0].legend(loc="upper right", fontsize=9)
    axes[0].set_title("CP failure shape = 503 errors on minority side")

    axes[1].plot(
        seconds,
        cp_ts.get("spread_per_sec", [0] * len(seconds)),
        color="#2980b9",
        linewidth=2,
        label=f"CP sync — max spread {cp_summary.get('max_value_spread_during_partition', 0)}",
    )
    axes[1].plot(
        seconds,
        ap_ts.get("spread_per_sec", [0] * len(seconds)),
        color="#8e44ad",
        linewidth=2,
        linestyle="--",
        label=f"AP local — max spread {ap_summary.get('max_value_spread_during_partition', 0)}",
    )
    axes[1].set_ylabel("Replica spread")
    axes[1].set_xlabel("Seconds into test")
    axes[1].set_ylim(bottom=0)
    axes[1].grid(axis="y", alpha=0.3)
    axes[1].legend(loc="upper right", fontsize=9)
    axes[1].set_title("AP failure shape = divergent values across replicas")

    for t in (p_start, p_end):
        for axis in axes:
            axis.axvline(t, color="#2c3e50", linestyle=":", linewidth=1.2, alpha=0.7)

    fig.text(
        0.5,
        0.01,
        f"partition window: t={p_start}s → t={p_end}s  |  "
        f"CP: errors↑ spread≈0  vs  AP: errors≈0 spread↑",
        ha="center",
        fontsize=10,
        color="#444444",
    )

    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=140)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Overlay CP vs AP partition run charts")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"))
    parser.add_argument("--nodes", type=int, default=3)
    parser.add_argument(
        "--cp-run",
        type=Path,
        help="CP (sync) partition run JSON (default: latest sync-n3-partition-*.json)",
    )
    parser.add_argument(
        "--ap-run",
        type=Path,
        help="AP partition run JSON (default: latest ap-n3-partition-*.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/runs/cp-vs-ap-partition.png"),
    )
    args = parser.parse_args()

    cp_path = args.cp_run or latest_partition_run(args.runs_dir, "sync", args.nodes)
    ap_path = args.ap_run or latest_partition_run(args.runs_dir, "ap", args.nodes)
    if cp_path is None or ap_path is None:
        raise SystemExit(
            "Need both sync and ap partition runs. "
            "Run: make load REPLICATION=sync PARTITION=1 && make load REPLICATION=ap PARTITION=1"
        )

    plot_compare(load_run(cp_path), load_run(ap_path), args.output)
    print(f"Wrote {args.output}")
    print(f"  CP: {cp_path.name}")
    print(f"  AP: {ap_path.name}")


if __name__ == "__main__":
    main()
