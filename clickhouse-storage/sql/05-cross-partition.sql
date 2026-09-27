-- EXP 5 — background merges never cross a partition boundary.
--
-- Same logical row, timestamps either side of a month boundary, so the two
-- versions land in different partitions. No background merge can ever
-- collapse them.
--
-- Read-time FINAL *does* rescue you by default -- but the common speedup
-- `do_not_merge_across_partitions_select_final=1` turns that off, and then
-- the numbers silently double.

DROP TABLE IF EXISTS ch_lab.parted;

CREATE TABLE ch_lab.parted
(
    tenant_id  String,
    order_id   String,
    amount     UInt32,
    created_at DateTime,
    updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, order_id);

INSERT INTO ch_lab.parted VALUES ('acme','ord-1',400,'2026-08-31 23:59:00','2026-09-16 10:00:00');
INSERT INTO ch_lab.parted VALUES ('acme','ord-1',950,'2026-09-01 00:01:00','2026-09-16 10:05:00');

OPTIMIZE TABLE ch_lab.parted FINAL;

SELECT '--- two partitions, permanently separate ---' AS step;
SELECT partition, count() AS parts, sum(rows) AS rows
FROM system.parts
WHERE database = 'ch_lab' AND table = 'parted' AND active
GROUP BY partition ORDER BY partition;

SELECT '--- three readings ---' AS step;
SELECT * FROM (
    SELECT 1 AS ord, 'no FINAL' AS q,
           count() AS rows, sum(amount) AS total
    FROM ch_lab.parted
    UNION ALL
    SELECT 2, 'FINAL (default)',
           count(), sum(amount)
    FROM ch_lab.parted FINAL
    UNION ALL
    SELECT 3, 'FINAL + do_not_merge_across_partitions=1',
           count(), sum(amount)
    FROM ch_lab.parted FINAL
    SETTINGS do_not_merge_across_partitions_select_final = 1
) ORDER BY ord;

-- Expected:
--   202608  1 part  1 row
--   202609  1 part  1 row
--   no FINAL                                  2  1350   WRONG
--   FINAL (default)                           1   950   right
--   FINAL + do_not_merge_across_partitions=1  2  1350   WRONG
--
-- THE COUPLING: partition key and dedup key are not independent. Enabling
-- that setting asserts "the partition expression is derived from immutable
-- columns". Partition on an event time fixed at creation -- never on a
-- last-updated time, never on anything a later write can recompute.
