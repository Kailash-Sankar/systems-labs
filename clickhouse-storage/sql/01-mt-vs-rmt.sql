-- EXP 1 — MergeTree vs ReplacingMergeTree, before any merge runs.
--
-- Two identical tables, one line different. The story: a row is written,
-- then recomputed and written again with a newer version.
--
-- Expect: BOTH engines return the duplicate. RMT is not a uniqueness
-- constraint -- it dedups at merge time, and no merge has run yet.

DROP TABLE IF EXISTS ch_lab.orders_mt;
DROP TABLE IF EXISTS ch_lab.orders_rmt;

CREATE TABLE ch_lab.orders_mt
(
    tenant_id  String,
    order_id   String,
    amount     UInt32,
    updated_at DateTime
)
ENGINE = MergeTree
ORDER BY (tenant_id, order_id);

CREATE TABLE ch_lab.orders_rmt
(
    tenant_id  String,
    order_id   String,
    amount     UInt32,
    updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)   -- version column
ORDER BY (tenant_id, order_id);           -- doubles as the dedup key

-- Merges off, so we observe the raw post-insert state.
SYSTEM STOP MERGES ch_lab.orders_mt;
SYSTEM STOP MERGES ch_lab.orders_rmt;

-- Separate statements on purpose: one INSERT = one part.
INSERT INTO ch_lab.orders_mt  VALUES ('acme','ord-1',400,'2026-09-16 10:00:00');
INSERT INTO ch_lab.orders_mt  VALUES ('acme','ord-1',950,'2026-09-16 10:05:00');
INSERT INTO ch_lab.orders_mt  VALUES ('acme','ord-2',120,'2026-09-16 10:06:00');

INSERT INTO ch_lab.orders_rmt VALUES ('acme','ord-1',400,'2026-09-16 10:00:00');
INSERT INTO ch_lab.orders_rmt VALUES ('acme','ord-1',950,'2026-09-16 10:05:00');
INSERT INTO ch_lab.orders_rmt VALUES ('acme','ord-2',120,'2026-09-16 10:06:00');

SELECT '--- one INSERT = one part ---' AS step;
SELECT table, count() AS parts, sum(rows) AS rows
FROM system.parts
WHERE database = 'ch_lab' AND table IN ('orders_mt','orders_rmt') AND active
GROUP BY table ORDER BY table;

SELECT '--- same data, three readings ---' AS step;
SELECT * FROM (
    SELECT 'MergeTree'      AS engine, count() AS rows, sum(amount) AS total FROM ch_lab.orders_mt
    UNION ALL
    SELECT 'RMT (no FINAL)' AS engine, count() AS rows, sum(amount) AS total FROM ch_lab.orders_rmt
    UNION ALL
    SELECT 'RMT FINAL'      AS engine, count() AS rows, sum(amount) AS total FROM ch_lab.orders_rmt FINAL
) ORDER BY engine;

-- Expected:
--   MergeTree      3  1470
--   RMT (no FINAL) 3  1470   <- the duplicate is still there
--   RMT FINAL      2  1070   <- 950 + 120, correct
