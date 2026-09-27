#!/usr/bin/env bash
#
# EXP 7 — why parts do not pile up.
#
# "One insert per second means 86,400 folders a day" is the natural fear,
# and it is wrong: merges collapse parts GEOMETRICALLY. Each round consumes
# a whole run of adjacent parts, so the count decays like a geometric
# series and the number of rounds is logarithmic in the number of inserts.
#
# 256 single-row inserts with merges paused, then un-paused. Watch what
# happens in the next few hundred milliseconds.

set -euo pipefail
cd "$(dirname "$0")"
source ./ch.sh
require_up

N=256

ch "DROP TABLE IF EXISTS ch_lab.churn"
ch "CREATE TABLE ch_lab.churn (id UInt32, s String) ENGINE = MergeTree ORDER BY id"
ch "SYSTEM STOP MERGES ch_lab.churn"

rule "$N separate inserts, merges paused"
for i in $(seq 1 $N); do
    ch "INSERT INTO ch_lab.churn VALUES ($i, 'row')"
done

ch "SELECT count() AS parts, max(level) AS max_level
    FROM system.parts WHERE database='ch_lab' AND table='churn' AND active" \
    --format PrettyCompactMonoBlock

rule "the bound the selector obeys"
ch "SELECT name, value FROM system.merge_tree_settings WHERE name='max_parts_to_merge_at_once'" \
    --format PrettyCompactMonoBlock

rule "SYSTEM START MERGES"
ch "SYSTEM START MERGES ch_lab.churn"
sleep 3

ch "SELECT count() AS parts, groupArray(rows) AS part_sizes, max(level) AS max_level
    FROM system.parts WHERE database='ch_lab' AND table='churn' AND active" \
    --format PrettyCompactMonoBlock

rule "what the merge pool actually did"
ch "SELECT event_time, length(merged_from) AS parts_merged_in, rows AS rows_out, duration_ms
    FROM system.part_log
    WHERE database='ch_lab' AND table='churn' AND event_type='MergeParts'
    ORDER BY event_time" --format PrettyCompactMonoBlock

cat <<'NOTES'

Expected:
  before:  256 parts, max_level 0
  after:     3 parts  [56,100,100], max_level 1   -- in under 200 ms
  part_log: three merges at the same second, parts_merged_in 56 / 100 / 100

Note it merged 100 parts AT A TIME, not pairwise -- bounded by
max_parts_to_merge_at_once = 100. So the decay base is ~100, not 2, and
three merges ran in parallel on separate pool threads.

  Linear (the fear)          256 parts -> 255 rounds,  1M -> 999,999
  Geometric, base 2          256 parts ->   8 rounds,  1M ->      20
  Geometric, base 100        256 parts ->   2 rounds,  1M ->       3

Two details the textbook picture misses:

1. It does NOT merge down to one part. It sits at [56,100,100]
   indefinitely. The selector acts on pressure -- rising part counts, or
   parts small relative to neighbours. Merging three big parts into one
   costs a full rewrite and buys almost nothing. Steady state is "a few
   parts", not "one".

2. Merge throughput scales with insert throughput, because merges are
   triggered by part count rather than a timer. Doubling writes roughly
   doubles merge activity and leaves the part count flat.

Falling behind means inserts genuinely outran the pool. The brakes, all
PER PARTITION -- which is the other reason over-partitioning is fatal:
  parts_to_delay_insert  1000    sleeps your INSERT to let merges catch up
  parts_to_throw_insert  3000    rejects it: "Too many parts"
  max_parts_in_total   100000    hard ceiling across all partitions
NOTES
