# clickhouse-storage

Hands-on lab for what happens underneath a ClickHouse schema: parts,
merges, dedup, and `FINAL`. Every claim in the plan is a measurement from
one of these scripts, not a paraphrase of the docs.

Phased plan: [`docs/clickhouse-storage-learning-plan.md`](docs/clickhouse-storage-learning-plan.md) — all 7 phases complete.

The lab answers questions that only show up once data is on disk: why a
`ReplacingMergeTree` still returns duplicates, why some duplicates can
never be removed, why an insert-per-second does not produce 86,400
folders, and why a projection you added is being silently ignored.

## Quick start

```bash
make up          # server on :8124 (HTTP) and :9001 (native)
make all         # run every experiment in order
make capture     # same, tee'd to data/runs/
make down
```

Ports are deliberately off the ClickHouse defaults so this can run
alongside another local server. Everything lives in a `ch_lab` database
that `make reset` drops and recreates; nothing outside it is touched.

## The experiments

| | What it shows | Result |
|---|---|---|
| `make exp1` | MergeTree vs RMT *before* a merge | both return the duplicate: 3 rows / 1470 |
| `make exp2` | the same tables after a merge | RMT correct without `FINAL`: 2 / 1070 |
| `make exp3` | `FINAL` on a plain MergeTree | `Code: 181 ILLEGAL_FINAL` |
| `make exp11` | dedup at read time instead | `LIMIT 1 BY` / `argMax` → 2 / 1070 |
| `make exp4` | mutable column in the dedup key | 2 / 1350 **after** `OPTIMIZE FINAL` — unfixable |
| `make exp5` | merges never cross a partition | `FINAL` 1 / 950, but 2 / 1350 with the cross-partition speedup |
| `make exp6` | `async_insert` coalescing | 8 parts → **1 part** |
| `make exp7` | the merge cascade | 256 parts → **`[56,100,100]`** in under a second |
| `make exp8` | Compact vs Wide parts | 10 files vs 22 files |
| `make exp9` | codecs | timestamp column **414× smaller**; table 8.60 MiB → 202 KiB |
| `make exp10` | projections | **1,000,000 → 8,192** rows read |
| `make exp12` | projection on an RMT | `Code: 344 SUPPORT_IS_DISABLED` |

`exp3` and `exp12` are *supposed* to fail — the error is the result, so
the Makefile ignores their exit status.

## Three findings worth the detour

**`Delta` is the wrong default for regular timestamps.** The folk rule is
"use `Delta` for timestamps". On a fixed sampling interval the deltas are
constant, so `DoubleDelta` reduces them to a run of zeros and wins by
**40×** over `Delta` — 18.90 KiB vs 755.55 KiB on the same 2M rows.

**`async_insert_busy_timeout_ms` is not the timeout.**
`async_insert_busy_timeout_max_ms` (default 200 ms) silently clamps it,
and `async_insert_use_adaptive_busy_timeout` shrinks it further. Setting
the obvious knob to 3000 gets you 200 ms and no error.

**Merges are not pairwise.** They consume up to
`max_parts_to_merge_at_once` (100) per round, so part counts decay with
base ~100, not 2 — and they settle at a few parts, never one.

## Makefile targets

| Target | Description |
|--------|-------------|
| `make up` | Start the server, wait for health, create `ch_lab` |
| `make down` | Stop the container |
| `make clean` | Stop and delete the volume |
| `make reset` | Drop and recreate `ch_lab` |
| `make shell` | Interactive `clickhouse-client` in `ch_lab` |
| `make logs` | Tail server logs |
| `make exp1` … `exp12` | Run one experiment |
| `make exp8-files` | Count real files in a Compact vs a Wide part |
| `make all` | Every experiment in phase order |
| `make capture` | `make all`, tee'd to `data/runs/run-<stamp>.txt` |

Copy `.env.sample` to `.env` to change ports. Run outputs land in
`data/runs/` (gitignored).

## Poking at it yourself

```sql
-- what the write path produced
SELECT table, partition, part_type, name, rows, level
FROM system.parts WHERE database = 'ch_lab' AND active ORDER BY table, name;

-- what the merge pool did
SELECT event_time, table, length(merged_from) AS merged_in, rows, duration_ms
FROM system.part_log WHERE database = 'ch_lab' AND event_type = 'MergeParts'
ORDER BY event_time DESC;

-- per-column bytes (group on `column`, NOT `name` — that is the part name)
SELECT table, column, formatReadableSize(sum(column_data_compressed_bytes))
FROM system.parts_columns WHERE database = 'ch_lab' AND active
GROUP BY table, column ORDER BY table, column;
```
