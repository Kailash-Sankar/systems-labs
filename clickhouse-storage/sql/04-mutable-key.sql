-- EXP 4 — a mutable column in the dedup key creates PERMANENT duplicates.
--
-- On a ReplacingMergeTree the ORDER BY tuple IS the identity of a row.
-- Here `region` arrives empty and is backfilled later -- so the two writes
-- have different keys and ClickHouse is correct to keep both.
--
-- Expect: 2 rows, 1350, even after OPTIMIZE FINAL *and* reading with FINAL.
-- Nothing fixes this. The table has to be rebuilt with a proper key.

DROP TABLE IF EXISTS ch_lab.bad_key;

CREATE TABLE ch_lab.bad_key
(
    tenant_id  String,
    region     String,   -- <-- MUTABLE, and it is in the ORDER BY
    order_id   String,
    amount     UInt32,
    updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (tenant_id, region, order_id);

INSERT INTO ch_lab.bad_key VALUES ('acme','',    'ord-1',400,'2026-09-16 10:00:00');
INSERT INTO ch_lab.bad_key VALUES ('acme','eu-1','ord-1',950,'2026-09-16 10:05:00');

OPTIMIZE TABLE ch_lab.bad_key FINAL;

SELECT '--- forced a full merge, then read with FINAL ---' AS step;
SELECT region, order_id, amount FROM ch_lab.bad_key FINAL ORDER BY region;

SELECT count() AS rows_after_optimize_and_final, sum(amount) AS total
FROM ch_lab.bad_key FINAL;

-- Expected:
--   ''     ord-1  400
--   'eu-1' ord-1  950
--   rows = 2, total = 1350
--
-- Contrast with EXP 1/2, where waiting for a merge fixed it. This is not
-- merge lag -- ('acme','','ord-1') and ('acme','eu-1','ord-1') are simply
-- different keys. Silent, and unreachable by any query.
--
-- RULE: an RMT's ORDER BY may contain only immutable identity columns.
--       Everything else is payload, however much it feels like identity.
