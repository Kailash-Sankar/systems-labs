#!/usr/bin/env bash
#
# EXP 6 — async_insert: the server-side buffer.
#
# One insert = one part. A writer doing many small inserts produces many
# tiny parts, and part count is what eventually rejects your writes. The
# classic fix is client-side batching; async_insert moves that buffer into
# the server instead.
#
# Two identical tables get 8 concurrent single-row inserts. Merges are
# stopped so we observe raw part counts.
#
# THE GOTCHA this script is shaped around: async inserts are grouped by
# (query text, settings, user). Inlining values into the SQL --
# VALUES (1,'a') vs VALUES (2,'a') -- makes every query text unique, so
# nothing coalesces. We therefore send ONE query shape and pipe the row in
# on stdin. Getting this wrong produces exactly the part explosion you were
# trying to avoid.
#
# Note also: this server has async_insert=1 as a server-level default, so
# the control table must pass --async_insert=0 explicitly.

set -euo pipefail
cd "$(dirname "$0")"
source ./ch.sh
require_up

N=8

ch "DROP TABLE IF EXISTS ch_lab.ins_sync"
ch "DROP TABLE IF EXISTS ch_lab.ins_async"
ch "CREATE TABLE ch_lab.ins_sync  (id UInt32, s String) ENGINE = MergeTree ORDER BY id"
ch "CREATE TABLE ch_lab.ins_async (id UInt32, s String) ENGINE = MergeTree ORDER BY id"
ch "SYSTEM STOP MERGES ch_lab.ins_sync"
ch "SYSTEM STOP MERGES ch_lab.ins_async"

rule "$N concurrent inserts, async_insert = 0 (control)"
for i in $(seq 1 $N); do
    echo "$i,row" | docker exec -i "$CONTAINER" clickhouse-client \
        --async_insert=0 \
        --query "INSERT INTO ch_lab.ins_sync FORMAT CSV" &
done
wait

rule "$N concurrent inserts, async_insert = 1"
for i in $(seq 1 $N); do
    echo "$i,row" | docker exec -i "$CONTAINER" clickhouse-client \
        --async_insert=1 \
        --wait_for_async_insert=1 \
        --async_insert_max_data_size=10000000 \
        --async_insert_busy_timeout_ms=3000 \
        --async_insert_busy_timeout_max_ms=5000 \
        --async_insert_use_adaptive_busy_timeout=0 \
        --query "INSERT INTO ch_lab.ins_async FORMAT CSV" &
done
wait

rule "result"
ch "SELECT table, count() AS parts, sum(rows) AS rows
    FROM system.parts
    WHERE database = 'ch_lab' AND table IN ('ins_sync','ins_async') AND active
    GROUP BY table ORDER BY table" --format PrettyCompactMonoBlock

cat <<'NOTES'

Expected:
  ins_sync    8 parts   8 rows     <- async_insert = 0
  ins_async   1 part    8 rows     <- async_insert = 1

THE SETTING THAT IS NOT THE SETTING -- worth the detour, because the
obvious tuning knob lies to you:

  async_insert_busy_timeout_ms        the value you think you are setting
  async_insert_busy_timeout_max_ms    a CEILING that silently clamps it
  async_insert_use_adaptive_busy_timeout  shrinks it further under light load

On a default server busy_timeout_max_ms is 200, so passing
busy_timeout_ms=3000 gets you 200 ms and nothing else. Check with:

  SELECT name, value FROM system.settings WHERE name LIKE 'async_insert%';

Spawning 8 `docker exec` clients takes longer than 200 ms, so without
raising the ceiling AND disabling the adaptive timeout this run produces
2 parts, not 1 -- still 4x better than sync, but not the clean result.
Real lesson: the flush window has to be wider than the gap between your
writes, and the window is not whichever number you set last.

A typical writer profile:
  async_insert                 = 1
  wait_for_async_insert        = 1          ack only after the flush hits disk
  async_insert_max_data_size   = 10000000   flush at ~10 MB...
  async_insert_busy_timeout_ms = 1000       ...or after 1s, whichever first

wait_for_async_insert = 0 returns in microseconds but silently loses rows
if the server dies before the flush. Keep it at 1 unless the data is
genuinely disposable.
NOTES
