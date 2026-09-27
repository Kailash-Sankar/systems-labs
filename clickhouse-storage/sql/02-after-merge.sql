-- EXP 2 — the same two tables after a merge actually runs.
--
-- Expect: MergeTree keeps all 3 rows; RMT collapses to 2 and is now
-- correct WITHOUT FINAL. Dedup is a property of merging, not of reading.
-- Run 01-mt-vs-rmt.sql first.

SYSTEM START MERGES ch_lab.orders_mt;
SYSTEM START MERGES ch_lab.orders_rmt;

OPTIMIZE TABLE ch_lab.orders_mt  FINAL;
OPTIMIZE TABLE ch_lab.orders_rmt FINAL;

SELECT '--- parts collapsed ---' AS step;
SELECT table, count() AS parts, sum(rows) AS rows
FROM system.parts
WHERE database = 'ch_lab' AND table IN ('orders_mt','orders_rmt') AND active
GROUP BY table ORDER BY table;

SELECT '--- RMT is now correct without FINAL ---' AS step;
SELECT * FROM (
    SELECT 'MergeTree'      AS engine, count() AS rows, sum(amount) AS total FROM ch_lab.orders_mt
    UNION ALL
    SELECT 'RMT (no FINAL)' AS engine, count() AS rows, sum(amount) AS total FROM ch_lab.orders_rmt
) ORDER BY engine;

-- Expected:
--   orders_mt   1 part  3 rows       MergeTree      3  1470
--   orders_rmt  1 part  2 rows       RMT (no FINAL) 2  1070
--
-- The lesson is the gap between EXP1 and EXP2: correctness arrived on a
-- background thread's schedule, not yours.
