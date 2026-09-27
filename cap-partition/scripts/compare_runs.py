#!/usr/bin/env python3
"""Compare latest healthy-network runs (sync vs async)."""

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table


def latest_run(runs_dir: Path, replication: str, nodes: int, partition: bool = False) -> Path | None:
    if partition:
        pattern = f"{replication}-n{nodes}-partition-*.json"
    else:
        pattern = f"{replication}-n{nodes}-*.json"
        matches = [
            p
            for p in sorted(runs_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            if "-partition-" not in p.name
        ]
        return matches[0] if matches else None
    matches = sorted(runs_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def load_summary(path: Path) -> dict:
    with path.open() as handle:
        data = json.load(handle)
    summary = data["summary"]
    summary["_file"] = path.name
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare sync vs async healthy runs")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"))
    parser.add_argument("--nodes", type=int, default=3)
    parser.add_argument(
        "--modes",
        default="sync,async",
        help="Comma-separated replication modes",
    )
    parser.add_argument(
        "--partition",
        action="store_true",
        help="Compare latest partition runs (-partition- in filename)",
    )
    args = parser.parse_args()

    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    console = Console()
    title = (
        f"Partition comparison (n{args.nodes}, latest runs)"
        if args.partition
        else f"Healthy network comparison (n{args.nodes}, latest runs)"
    )
    table = Table(title=title)
    table.add_column("Mode")
    if args.partition:
        table.add_column("errors (partition window)")
        table.add_column("spread (partition window)")
        table.add_column("p99 ms (partition window)")
    else:
        table.add_column("p99 write ms")
        table.add_column("stale reads")
    table.add_column("errors (total)")
    table.add_column("max spread")
    table.add_column("run file")

    for mode in modes:
        path = latest_run(args.runs_dir, mode, args.nodes, partition=args.partition)
        if path is None:
            blanks = ("—", "—", "—", "—", "—") if args.partition else ("—", "—", "—", "—")
            table.add_row(mode, *blanks, "(no run)")
            continue
        summary = load_summary(path)
        if args.partition:
            p99_part = summary.get("p99_during_partition_ms")
            p99_str = f"{p99_part:.1f}" if p99_part is not None else "—"
            table.add_row(
                mode,
                str(summary.get("errors_during_partition", 0)),
                str(summary.get("max_value_spread_during_partition", 0)),
                p99_str,
                str(summary.get("errors_total", 0)),
                str(summary.get("max_value_spread", 0)),
                summary["_file"],
            )
        else:
            table.add_row(
                mode,
                f"{summary.get('p99_write_ms', 0):.1f}",
                str(summary.get("stale_read_count", "—")),
                str(summary.get("errors_total", 0)),
                str(summary.get("max_value_spread", 0)),
                summary["_file"],
            )

    console.print(table)


if __name__ == "__main__":
    main()
