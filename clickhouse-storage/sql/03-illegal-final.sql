-- EXP 3 — FINAL on a plain MergeTree is not slow, it is illegal.
--
-- Worth knowing before migrating a table from RMT to MergeTree: every
-- stale FINAL in application SQL becomes a hard error, not a slowdown.
--
-- Expect: Code: 181. DB::Exception: Storage MergeTree doesn't support FINAL.

SELECT count() FROM ch_lab.orders_mt FINAL;
