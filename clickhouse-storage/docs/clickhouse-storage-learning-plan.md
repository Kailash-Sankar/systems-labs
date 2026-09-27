# ClickHouse Storage Internals — Plan

Hands-on lab for the layer underneath the schema: how rows physically land
on disk, what background merges do to them, and why that explains most of
the surprises — wrong `sum()`, duplicates that never go away, `Too many
parts`, a projection that never fires.

Everything here is measured against a local server. No numbers in this
plan are illustrative; each one is pasted from a run of the matching
experiment.

---

## Context: Learning Exercise vs Production

This is a **single-node** lab. Replication, sharding, distributed tables,
and keeper are all out of scope — they change the operational story but
not the storage mechanics, which is what we are after.

**Why a scratch database rather than a real dataset:** every experiment
needs a known-exact answer (`2 rows, total 1070`) so a wrong result is
unmistakable. Synthetic rows make the assertions crisp and the runs fast.

**Why we do not benchmark:** this lab measures *structural* quantities —
part counts, rows read, bytes on disk — which are deterministic and
meaningful on a laptop. Wall-clock throughput on a container sharing a
Docker VM with everything else is not, so timings appear only where the
ratio is large enough to survive the noise.

Stop when the Phase 7 recap table feels obvious. Distributed ClickHouse,
materialized views as a write path, and query-plan tuning are separate
topics.

---

## Vocabulary

### Storage units

| Term | Meaning |
|------|---------|
| **Part** | One insert's worth of rows: an immutable folder of column files, sorted by `ORDER BY`. |
| **Partition** | A group of parts sharing a `PARTITION BY` value. Merges never cross this boundary. |
| **Granule** | 8192 rows; the unit the sparse primary index points at, and the smallest thing a read can skip to. |
| **Merge** | Background rewrite of several adjacent parts into one bigger part. |
| **Level** | How many merge generations a part has been through. A fresh insert is level 0. |
| **Compact / Wide** | Part formats. Compact = all columns in one file; Wide = a file per column. Switched by `min_bytes_for_wide_part`. |

### Engines and dedup

| Term | Meaning |
|------|---------|
| **MergeTree** | Merges parts, keeps every row. |
| **ReplacingMergeTree(ver)** | Merges parts and keeps only `max(ver)` per `ORDER BY` tuple. |
| **Dedup key** | Not a separate declaration — it *is* the `ORDER BY` tuple. |
| **`FINAL`** | Run the engine's merge logic at read time, in memory, then throw it away. |
| **Dedup at read** | `LIMIT 1 BY key ORDER BY ver DESC` — the same thing, hand-rolled per query. |

### Write and read shaping

| Term | Meaning |
|------|---------|
| **`async_insert`** | Server-side buffer that coalesces many small inserts into one part. |
| **Codec** | Per-column compression. A scan-bandwidth lever, not only a disk lever. |
| **Projection** | A second physical sort order of the same rows, inside the table, chosen by the optimizer. |

---

## Concept map

```
        INSERT
          │
          ├── async_insert buffer ──┐        (Phase 4)
          │                         │
          ▼                         ▼
        one PART per insert/flush ────────── immutable, sorted by ORDER BY
          │                                   Compact or Wide   (Phase 5)
          │                                   per-column codecs (Phase 6)
          ▼
        background MERGE  ── bounded by max_parts_to_merge_at_once
          │                  never crosses a PARTITION   (Phase 3)
          │
          ├── MergeTree ........... keep every row       (Phase 2)
          └── ReplacingMergeTree .. keep max(version)     (Phase 2)
                  │
                  └── not yet merged? ──► FINAL at read time (Phase 2)
                                          or LIMIT 1 BY      (Phase 2)

        SELECT
          ├── partition pruning ─── skip whole directories
          ├── sparse index ──────── skip granules inside surviving parts
          └── projection ────────── read a differently-sorted copy (Phase 7)
                                    ...but never together with FINAL
```

---

## Fixed setup (same for every phase)

| Item | Value | Why |
|------|-------|-----|
| Server | Single node, pinned image, own ports (8124/9001) | Runs alongside another local ClickHouse without a clash |
| Database | `ch_lab`, dropped and recreated by `make reset` | Nothing outside it is ever touched |
| Dedup fixture | 3 rows: `ord-1` written twice (400 then 950), `ord-2` once (120) | Correct answer is always **2 rows / 1070**; wrong is **3 / 1470** |
| Scale fixture | 1M spans / 2M timestamped rows | Large enough that granule skipping and codec ratios are unambiguous |
| Merge control | `SYSTEM STOP MERGES` where timing matters | Makes "before the merge" observable instead of a race |

**What to watch:** `system.parts` (part count, rows, level, part_type),
`system.parts_columns` (per-column bytes), `system.part_log` (what the
merge pool actually did), `system.query_log` (rows actually read).

---

## Write-up workflow (each phase)

Two write-ups, two jobs. This plan is the lab record; a separate personal
notes wiki (kept outside this repo) is the concept refresher.

| Where | Purpose |
|-------|---------|
| **This plan** (`docs/clickhouse-storage-learning-plan.md`) | Measured numbers, status table, repo-specific commands |
| **Personal notes** (outside this repo) | Vocabulary, what clicked, recap tables; prose over raw metrics |

**After every phase session:**

1. Run the phase; fill the **Phase doc block** below with measured results.
2. Carry the same block into the personal notes, stripped of repo paths.
3. Add one **Takeaway** line under that block.
4. Tick the phase in the **Status** table at the bottom.

---

## Repo layout

```
clickhouse-storage/
├── docker-compose.yml         single CH node on 8124/9001
├── Makefile                   make up / make expN / make all / make capture
├── docs/
│   └── clickhouse-storage-learning-plan.md
├── sql/
│   ├── 00-reset.sql           drop + recreate ch_lab
│   ├── 01-mt-vs-rmt.sql       Phase 2
│   ├── 02-after-merge.sql     Phase 2
│   ├── 03-illegal-final.sql   Phase 2   (expected to fail)
│   ├── 04-mutable-key.sql     Phase 3
│   ├── 05-cross-partition.sql Phase 3
│   ├── 08-part-formats.sql    Phase 5
│   ├── 09-codecs.sql          Phase 6
│   ├── 10-projections.sql     Phase 7
│   ├── 11-read-dedup.sql      Phase 2
│   └── 12-projection-on-rmt.sql Phase 7 (expected to fail)
└── scripts/
    ├── ch.sh                  one place that knows how to reach the server
    ├── exp06_async_insert.sh  Phase 4 — needs concurrent clients
    └── exp07_merge_cascade.sh Phase 5 — needs 256 discrete inserts
```

Two experiments are shell rather than SQL because they need orchestration
a single script cannot express: **06** must issue concurrent inserts with
*identical query text* (async grouping depends on it), and **07** needs
256 separate insert statements with merges paused in between.

---

## Phase 1 — Parts and the Write Path

**Session goal:** see that an insert produces a folder, and that the folder
count is the number you have to care about.

### Tasks

1. `make up` — server on 8124, `ch_lab` created.
2. `make exp1` and read only the first table: three inserts, three parts.
3. Inspect the part names: `all_1_1_0`, `all_2_2_0`, … — `all` is the
   partition (no partition key), then block range, then merge level.

### Concepts to learn

| Concept | Point |
|---------|-------|
| One insert = one part | The write path does no coordination; it appends a folder |
| Immutability | There is no `UPDATE`; there is only "write another part" and "decide what merging means" |
| Part naming | `202608_1_9_2` = partition, blocks 1–9, level 2 |

### Phase doc block (fill in after run)

**What we tried:** three single-row inserts into an empty MergeTree table.

**Result:** 3 parts, 3 rows, all at level 0.

**Takeaway:** Every behaviour in this lab falls out of one fact — an insert
writes an immutable sorted folder, and a background pool merges folders.

---

## Phase 2 — MergeTree vs ReplacingMergeTree, and `FINAL`

**Session goal:** internalise that RMT is not a uniqueness constraint.

### Tasks

1. `make exp1` — the same three writes into both engines, merges paused.
2. `make exp2` — start merges, `OPTIMIZE FINAL`, read again.
3. `make exp3` — `FINAL` on a plain MergeTree.
4. `make exp11` — the query-level alternative.

### Concepts to learn

| Concept | Point |
|---------|-------|
| Dedup happens at merge | Not at insert, not automatically at read |
| The gap | Between EXP1 and EXP2, correctness arrived on a background thread's schedule |
| `FINAL` cost | Driven by overlapping parts in the key range, not table size |
| `ILLEGAL_FINAL` | On plain MergeTree it is an error, not a slowdown |
| Two places to dedup | Table-level contract (`FINAL`) vs query-level opt-in (`LIMIT 1 BY`) |

### Phase doc block (fill in after run)

**What we tried:** `ord-1` written twice (400 then 950) plus `ord-2` (120),
into a `MergeTree` and a `ReplacingMergeTree(updated_at)`.

**Result, before any merge:**

| Reading | rows | total |
|---------|------|-------|
| MergeTree | 3 | 1470 |
| RMT, no `FINAL` | 3 | 1470 |
| RMT `FINAL` | 2 | 1070 |

**Result, after `OPTIMIZE FINAL`:** `orders_mt` 1 part / 3 rows;
`orders_rmt` 1 part / 2 rows. RMT now returns 2 / 1070 *without* `FINAL`.

`FINAL` on the MergeTree: `Code: 181 ... doesn't support FINAL (ILLEGAL_FINAL)`.

`LIMIT 1 BY event_id` and `argMax(amount, updated_at)` both give 2 / 1070
on a plain MergeTree.

**Takeaway:** `ReplacingMergeTree` is eventual cleanup, not a constraint —
until a merge runs, a plain `SELECT` returns duplicates and your `sum()` is
wrong.

---

## Phase 3 — Dedup Key Hazards

**Session goal:** find the two ways to build a table whose duplicates are
permanent.

### Tasks

1. `make exp4` — put a mutable column in the `ORDER BY`, then try to fix it.
2. `make exp5` — split one logical row across two partitions.
3. For exp5, read three ways: no `FINAL`, `FINAL`, and `FINAL` with
   `do_not_merge_across_partitions_select_final = 1`.

### Concepts to learn

| Concept | Point |
|---------|-------|
| `ORDER BY` is identity | On an RMT it may contain only immutable columns |
| Not merge lag | Waiting does not help; the keys genuinely differ |
| Merges are per-partition | Always, without exception |
| `FINAL` crosses partitions | By default — which is what rescues you |
| The coupling | The cross-partition speedup asserts your partition expression is immutable |

### Phase doc block (fill in after run)

**What we tried:** (a) `ORDER BY (tenant_id, region, order_id)` where
`region` arrives empty and is backfilled; (b) one logical row whose two
versions have `created_at` either side of a month boundary.

**Result (a):** 2 rows / 1350 *after* `OPTIMIZE FINAL` **and** reading with
`FINAL`. Unfixable by any query.

**Result (b):** partitions 202608 and 202609, one part each.

| Reading | rows | total | |
|---------|------|-------|---|
| no `FINAL` | 2 | 1350 | wrong |
| `FINAL` (default) | 1 | 950 | right |
| `FINAL` + `do_not_merge_across_partitions=1` | 2 | 1350 | wrong |

**Takeaway:** Partition key and dedup key are not independent — enabling the
cross-partition `FINAL` speedup silently doubles your numbers unless the
partition expression is derived from immutable columns.

---

## Phase 4 — Insert Shape: `async_insert`

**Session goal:** move batching into the server, and find the setting that
lies to you.

### Tasks

1. `make exp6` — 8 concurrent single-row inserts into two identical tables.
2. Read `system.settings WHERE name LIKE 'async_insert%'` before believing
   any timeout you set.

### Concepts to learn

| Concept | Point |
|---------|-------|
| Grouping key | (query text, settings, user) — inline `VALUES` literals defeat it |
| `wait_for_async_insert` | 1 = durable ack; 0 = microseconds and silent loss on crash |
| The clamp | `async_insert_busy_timeout_max_ms` caps `async_insert_busy_timeout_ms` |
| Adaptive timeout | `async_insert_use_adaptive_busy_timeout` shrinks it further under light load |

### Phase doc block (fill in after run)

**What we tried:** 8 concurrent inserts, merges paused, identical query text
with the row piped on stdin; control table forced to `async_insert=0`
because the server default is `1`.

**Result:** `ins_sync` 8 parts / 8 rows; `ins_async` 1 part / 8 rows.

**Detour that mattered:** the first runs gave `ins_async` = 2 parts. Cause
was not the 1s timeout — `async_insert_busy_timeout_max_ms` defaults to
**200 ms** and silently clamps whatever you pass, with the adaptive timeout
shrinking it further. Raising the ceiling *and* setting
`async_insert_use_adaptive_busy_timeout=0` produced the clean 1 part.

**Takeaway:** The flush window must be wider than the gap between your
writes — and it is not whichever number you set last, because a separate
ceiling setting overrides it.

---

## Phase 5 — Merge Cascade and Part Formats

**Session goal:** kill the "86,400 folders a day" fear with a measurement.

### Tasks

1. `make exp7` — 256 inserts with merges paused, then un-paused.
2. Read `system.part_log` to see how many parts each merge consumed.
3. `make exp8` then `make exp8-files` — Compact vs Wide, and real file counts.

### Concepts to learn

| Concept | Point |
|---------|-------|
| Geometric decay | Not pairwise: up to `max_parts_to_merge_at_once` per round |
| Steady state | "A few parts", not one — the selector acts on pressure |
| Self-balancing | Merges are triggered by part count, so throughput scales with writes |
| Backpressure | `parts_to_delay_insert` / `parts_to_throw_insert`, **per partition** |
| Part formats | Per-column files are only paid for once a part earns it |

### Phase doc block (fill in after run)

**What we tried:** 256 single-row inserts, merges stopped, then
`SYSTEM START MERGES`.

**Result:** 256 parts / level 0 → **3 parts `[56,100,100]`** / level 1, in
under a second. `system.part_log` shows three merges in the same second
consuming 56, 100 and 100 parts, in 22 / 42 / 38 ms.
`max_parts_to_merge_at_once = 100`.

| Model | rounds for 256 | rounds for 1M |
|-------|---------------|---------------|
| Linear (the fear) | 255 | 999,999 |
| Geometric, base 2 | 8 | 20 |
| **Geometric, base 100 (actual)** | **2** | **3** |

**Part formats:** `min_bytes_for_wide_part = 10485760`.

| Table | format | rows | size | files on disk |
|-------|--------|------|------|---------------|
| `small_part` | Compact | 100 | 1.53 KiB | **10** |
| `big_part` | Wide | 1,000,000 | 83.25 MiB | **22** |

**Takeaway:** Part counts decay geometrically with base ~100 and settle at a
few parts per partition, so "millions of tiny files" requires the part
count to run away first.

---

## Phase 6 — Codecs

**Session goal:** treat compression as a query-speed setting, and test the
folk rule instead of repeating it.

### Tasks

1. `make exp9` Part A — three codecs on one timestamp column.
2. Part B — whole-table default vs tuned.
3. Group on `column` and sum `column_data_compressed_bytes`; grouping on
   `name` gives the *part* name and nonsense numbers.

### Concepts to learn

| Concept | Point |
|---------|-------|
| Bandwidth = time | Query time is largely bytes read; halving bytes ~halves scan |
| `Delta` vs `DoubleDelta` | Delta encodes `v[i]-v[i-1]`; DoubleDelta encodes the change *in* the delta |
| Data shape, not type | The right codec follows the distribution, not the column type |
| `T64` | Transposes the bit matrix so unused high bits vanish |

### Phase doc block (fill in after run)

**What we tried:** 2M rows, one timestamp per millisecond in a table sorted
by time — so the deltas are a constant 1, the easiest possible input.

**Result, Part A (same column, three codecs):**

| Codec | on disk | ratio |
|-------|---------|-------|
| default (LZ4) | 7.64 MiB | 2.0 |
| `Delta, ZSTD(1)` | 755.55 KiB | 20.7 |
| **`DoubleDelta, ZSTD(1)`** | **18.90 KiB** | **826.7** |

**Result, Part B (whole table):**

| Column | default | tuned | smaller by |
|--------|---------|-------|-----------|
| `ts` | 7.64 MiB | 18.90 KiB | **413.8×** |
| `txt` | 466.00 KiB | 44.48 KiB | 10.5× |
| `n` | 515.19 KiB | 138.89 KiB | 3.7× |
| **whole table** | **8.60 MiB** | **202.27 KiB** | **~43×** |

**Correction this phase produced:** "use `Delta` for timestamps" is the folk
rule and it left **40×** on the table here. For a fixed sampling interval
the deltas are constant, so `DoubleDelta` reduces them to a run of zeros.
Use `Delta` for timestamps that drift, `DoubleDelta` for a fixed stride.

**Takeaway:** The timestamp went from the largest column in the table to a
rounding error — and it is the column you filter and bucket by in every
query.

---

## Phase 7 — Projections, and the Full Recap

**Session goal:** get a second sort order for free, then learn the one
combination that silently wastes it.

### Tasks

1. `make exp10` — 1M spans, projection on a second key, `EXPLAIN` + `rows_read`.
2. `make exp12` — try to put a projection on a `ReplacingMergeTree`.
3. Fill the master recap table below.

### Concepts to learn

| Concept | Point |
|---------|-------|
| Sort order, not absence | `visit_id` *is* a column; the problem is it is not in `ORDER BY` |
| Optimizer-selected | The query does not mention the projection |
| `FINAL` never uses one | So on an RMT it is pure cost |
| Rejected outright | `deduplicate_merge_projection_mode = 'throw'` is the default |

### Phase doc block (fill in after run)

**What we tried:** 1M spans, base `ORDER BY (tenant_id, request_id, span_id)`,
`PROJECTION by_visit ORDER BY (tenant_id, visit_id, request_id, span_id)`.
One visit selected.

**Result:**

| Mode | rows read | bytes read | elapsed |
|------|-----------|-----------|---------|
| projection | **8,192** | 159.41 KiB | 0.007 s |
| full scan | **1,000,000** | 16.42 MiB | 0.302 s |

122× fewer rows; `EXPLAIN` shows `ReadFromMergeTree (by_visit)` and
`Granules: 1/123`.

**Projection on an RMT:** `Code: 344 ... Projections are not supported for
ReplacingMergeTree with deduplicate_merge_projection_mode = throw
(SUPPORT_IS_DISABLED)`.

**Takeaway:** Projections give a second sort order the optimizer picks for
free — but `FINAL` never uses one, so they belong on plain `MergeTree`
tables only.

---

### Master recap

| Question | Lever | Cost | Phase | Measured |
|----------|-------|------|-------|----------|
| Is this row unique? | `ReplacingMergeTree(ver)` | Dedup only at merge time | 2 | 3 / 1470 → 2 / 1070 after merge |
| Read it correctly *now*? | `FINAL` | Overlapping parts in key range | 2 | `ILLEGAL_FINAL` on plain MergeTree |
| …without `FINAL`? | `LIMIT 1 BY` / `argMax` | Rows read; dupes stay on disk | 2 | 2 / 1070 on a plain MergeTree |
| Why won't dupes collapse? | Mutable column in `ORDER BY` | Permanent, unfixable | 3 | 2 / 1350 after `OPTIMIZE FINAL` |
| Why won't dupes collapse? | Versions in different partitions | `FINAL` saves you — unless disabled | 3 | 1 / 950 vs 2 / 1350 |
| Too many small inserts? | `async_insert` | Flush-window latency | 4 | 8 parts → 1 part |
| Will parts pile up? | Nothing — merges cascade | Decay base ~100 | 5 | 256 → `[56,100,100]` |
| Too many files? | Compact vs Wide parts | Auto at 10 MB | 5 | 10 files vs 22 files |
| Scans too slow? | Per-column codecs | Write CPU | 6 | table 8.60 MiB → 202 KiB |
| Second hot access path? | Projection | Disk + write bandwidth | 7 | 1,000,000 → 8,192 rows read |
| Projection on an RMT? | **Not allowed** | — | 7 | `Code: 344` |

### Decision tree (whiteboard this)

```
Are rows ever rewritten?
├── no  ──> MergeTree
│           └── occasional redelivery? dedup in the one query that cares
│           └── second hot sort order? add a PROJECTION
└── yes ──> ReplacingMergeTree(version)
            ├── ORDER BY must be IMMUTABLE columns only
            ├── PARTITION BY must be immutable too, if you enable
            │   do_not_merge_across_partitions_select_final
            └── no projections — build a second table instead

Writing many small batches?  ──> async_insert, and check the
                                 busy_timeout_max_ms ceiling

Scans feel slow?  ──> codecs before hardware; match the data's shape
```

### Design checklist

1. **Denormalise.** Unused columns are free to skip in a column store.
2. **`ORDER BY` is your index and your identity.** Lead with what you always
   filter on; the prefix rule is absolute.
3. **On an RMT, `ORDER BY` is the dedup key — immutable columns only.**
4. **Only choose RMT if rows are actually rewritten.**
5. **Partition by time, in the tens.** Never by a high-cardinality id.
6. **Keep the partition expression immutable** if you rely on the
   cross-partition `FINAL` speedup.
7. **Batch inserts**, or let `async_insert` do it — with stable query text.
8. **Set codecs deliberately**, matching data shape rather than column type.
9. **Projections only on plain `MergeTree`.**

---

## Takeaways (check you can say these)

- A part is one insert's worth of sorted, immutable columnar files; merges
  combine them continuously. Partitions contain parts and never merge
  across each other — that one boundary explains both cheap
  `DROP PARTITION` and the cross-partition dedup hole.
- `ReplacingMergeTree` is not a uniqueness constraint. It is eventual
  cleanup at merge time, and until a merge runs your `sum()` is wrong.
- `FINAL` runs merge logic at read time; its cost scales with overlapping
  parts in the key range, not table size — which is why batching inserts is
  a *read* optimisation.
- A mutable column in an RMT's `ORDER BY` creates duplicates that neither
  `OPTIMIZE` nor `FINAL` can repair, because the keys genuinely differ.
- Part counts decay geometrically with base ~100, not 2, and settle at a
  few parts per partition rather than one.
- Compression is a speed setting: the right codec for a fixed-stride
  timestamp beat the default by 414×, and `DoubleDelta` beat the
  conventional `Delta` advice by 40×.
- Projections give a second sort order the optimizer picks for free, but
  `FINAL` never uses one and an RMT refuses to have one at all.
- The settings that shape the write path can override each other:
  `async_insert_busy_timeout_max_ms` silently clamps the timeout you
  actually set.

---

## Out of scope (deliberately)

| Topic | Why not here |
|-------|--------------|
| Replication / sharding / keeper | Changes operations, not storage mechanics |
| Materialized views as a write path | Own topic; deserves its own lab |
| `Distributed` tables and query routing | Needs a cluster to be meaningful |
| Mutations (`ALTER UPDATE/DELETE`) | Follow-up after the parts model is solid |
| Query-plan tuning / join algorithms | Read path, not storage layer |
| Throughput benchmarking | A laptop Docker VM cannot produce honest numbers |

---

## Status

| Phase | Status |
|-------|--------|
| 1 — Parts and the write path | done |
| 2 — MergeTree vs RMT, and FINAL | done |
| 3 — Dedup key hazards | done |
| 4 — Insert shape: async_insert | done |
| 5 — Merge cascade and part formats | done |
| 6 — Codecs | done |
| 7 — Projections and full recap | done |

---

## References (external)

- ClickHouse docs — MergeTree engine family, table settings, codecs
- `system.parts`, `system.parts_columns`, `system.part_log`,
  `system.query_log`, `system.merge_tree_settings`, `system.settings`
