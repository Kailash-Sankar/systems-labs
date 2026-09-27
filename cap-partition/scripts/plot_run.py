#!/usr/bin/env python3
"""Render a cap-partition run JSON as a teaching chart."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def load_run(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def plot_run(run: dict, output: Path) -> None:
    ts = run["timeseries"]
    seconds = ts["seconds"]
    errors = ts["errors_per_sec"]
    spread = ts.get("spread_per_sec", [0] * len(seconds))
    summary = run["summary"]
    partition = run.get("partition", {})
    p_start = partition.get("start_sec")
    p_end = partition.get("end_sec")

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    title = (
        f"CAP partition — {run['replication']}, {run.get('nodes', 1)} nodes  "
        f"(errors during partition: {summary.get('errors_during_partition', 0)}, "
        f"max spread during partition: {summary.get('max_value_spread_during_partition', 0)})"
    )
    fig.suptitle(title, fontsize=12)

    axes[0].bar(seconds, errors, width=0.85, color="#c0392b", alpha=0.85)
    axes[0].set_ylabel("Errors / sec")
    axes[0].set_ylim(bottom=0)
    axes[0].grid(axis="y", alpha=0.3)
    axes[0].set_title("503 rate — CP shows up as errors during partition")

    axes[1].plot(seconds, spread, color="#8e44ad", linewidth=2, marker="o", markersize=3)
    axes[1].set_ylabel("Replica spread")
    axes[1].set_xlabel("Seconds into test")
    axes[1].set_ylim(bottom=0)
    axes[1].grid(axis="y", alpha=0.3)
    axes[1].set_title("Max score spread across replicas (internal poll)")

    if partition.get("enabled") and p_start is not None and p_end is not None:
        for t in (p_start, p_end):
            for axis in axes:
                axis.axvline(t, color="#2c3e50", linestyle="--", linewidth=1.2, alpha=0.8)
        fig.text(
            0.5,
            0.01,
            f"partition window: t={p_start}s → t={p_end}s",
            ha="center",
            fontsize=9,
            color="#555555",
        )

    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=140)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a cap-partition run JSON")
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
