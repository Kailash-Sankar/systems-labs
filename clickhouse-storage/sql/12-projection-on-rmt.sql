-- EXP 12 — projections and ReplacingMergeTree do not combine.
--
-- Two independent reasons, and this file demonstrates the hard one.
--
--   1. FINAL never uses a projection. The planner refuses. So on an RMT a
--      projection would cost disk and write bandwidth while every
--      correctness-sensitive query silently ignored it.
--
--   2. On recent versions the table will not even be created.
--
-- Expect: Code: 344 SUPPORT_IS_DISABLED.
--
-- The failure mode when it IS allowed (mode 'drop' or 'rebuild') is worse
-- than a slowdown: the projection and the base table drift apart, and
-- which answer you get depends on which the optimizer picked.
--
-- RULE: projections require a plain MergeTree. Need a differently-sorted
--       read path on an RMT? Build a separate table, not a projection.

SELECT value AS deduplicate_merge_projection_mode
FROM system.merge_tree_settings
WHERE name = 'deduplicate_merge_projection_mode';

CREATE TABLE ch_lab.proj_on_rmt
(
    a String,
    b String,
    v DateTime,
    PROJECTION p (SELECT * ORDER BY b)
)
ENGINE = ReplacingMergeTree(v)
ORDER BY a;
