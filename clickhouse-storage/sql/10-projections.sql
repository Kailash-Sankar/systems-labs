-- EXP 10 — projections: a second physical sort order inside the table.
--
-- Spans are sorted by request, but "all spans in one visit" is equally hot.
-- Note visit_id IS a column -- the problem is sort order, not absence. The
-- only index is the sparse index over ORDER BY, and request_id is a UUID,
-- so one visit's spans are scattered uniformly and no granule can be
-- skipped.
--
-- A projection is maintained automatically and chosen by the optimizer
-- without the query mentioning it.

DROP TABLE IF EXISTS ch_lab.spans;

CREATE TABLE ch_lab.spans
(
    tenant_id   String,
    visit_id    String,
    request_id  UUID,
    span_id     UUID,
    duration_ms UInt32,

    PROJECTION by_visit
    (
        SELECT * ORDER BY (tenant_id, visit_id, request_id, span_id)
    )
)
ENGINE = MergeTree
ORDER BY (tenant_id, request_id, span_id);

INSERT INTO ch_lab.spans
SELECT 'acme',
       concat('visit-', toString(number % 5000)),
       generateUUIDv4(),
       generateUUIDv4(),
       rand() % 2000
FROM numbers(1000000);

OPTIMIZE TABLE ch_lab.spans FINAL;

SELECT '--- the optimizer picks the projection ---' AS step;
EXPLAIN indexes = 1
SELECT count() FROM ch_lab.spans WHERE tenant_id = 'acme' AND visit_id = 'visit-4242';

-- Run the same query both ways, tagged so we can find them in query_log.
SELECT count() FROM ch_lab.spans
WHERE tenant_id = 'acme' AND visit_id = 'visit-4242'
SETTINGS optimize_use_projections = 1, log_comment = 'exp10_with_projection';

SELECT count() FROM ch_lab.spans
WHERE tenant_id = 'acme' AND visit_id = 'visit-4242'
SETTINGS optimize_use_projections = 0, log_comment = 'exp10_no_projection';

SYSTEM FLUSH LOGS;

SELECT '--- rows actually read ---' AS step;
SELECT
    if(log_comment = 'exp10_with_projection', 'projection', 'full scan') AS mode,
    read_rows,
    formatReadableSize(read_bytes) AS read_bytes,
    round(query_duration_ms / 1000, 4)                                   AS elapsed_s
FROM system.query_log
WHERE type = 'QueryFinish'
  AND log_comment IN ('exp10_with_projection','exp10_no_projection')
ORDER BY event_time DESC, mode
LIMIT 2;

-- Expected:
--   EXPLAIN shows  ReadFromMergeTree (by_visit)   <- not the base table
--   projection     8,192 rows read   (one granule)
--   full scan  1,000,000 rows read
--   -> 122x fewer rows read; the ratio grows with table size
--
-- THE INCOMPATIBILITY that catches people:
--   1. FINAL never uses a projection -- the planner refuses. On an RMT a
--      projection costs disk and write bandwidth while every
--      correctness-sensitive query silently ignores it.
--   2. On recent versions it will not even be created: the default
--      deduplicate_merge_projection_mode='throw' rejects adding a
--      projection to a ReplacingMergeTree.
--
-- RULE: projections require a plain MergeTree. Need a differently-sorted
--       read path on an RMT? Build a separate table, not a projection.
