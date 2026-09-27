-- EXP 9 — codecs are a QUERY SPEED lever, not just a storage one.
--
-- In a column store, query time is largely disk-read bandwidth. Halving
-- bytes on disk roughly halves scan time. Default is LZ4 for everything;
-- matching the codec to the DATA SHAPE does much better.
--
-- Part A compares three codecs on one timestamp column, because "use
-- Delta for timestamps" is the common advice and it is only half right.
-- Part B does a whole-table default-vs-tuned comparison.

DROP TABLE IF EXISTS ch_lab.ts_lz4;
DROP TABLE IF EXISTS ch_lab.ts_delta;
DROP TABLE IF EXISTS ch_lab.ts_dd;

-- ---------------------------------------------------------------- Part A
-- Same 2M timestamps, one per millisecond, in a table sorted by time.
-- The deltas are therefore a constant 1 -- the easiest possible input.

CREATE TABLE ch_lab.ts_lz4   (ts DateTime64(3))                                ENGINE = MergeTree ORDER BY ts;
CREATE TABLE ch_lab.ts_delta (ts DateTime64(3) CODEC(Delta,       ZSTD(1)))    ENGINE = MergeTree ORDER BY ts;
CREATE TABLE ch_lab.ts_dd    (ts DateTime64(3) CODEC(DoubleDelta, ZSTD(1)))    ENGINE = MergeTree ORDER BY ts;

INSERT INTO ch_lab.ts_lz4   SELECT toDateTime64('2026-09-01 00:00:00',3) + interval number millisecond FROM numbers(2000000);
INSERT INTO ch_lab.ts_delta SELECT toDateTime64('2026-09-01 00:00:00',3) + interval number millisecond FROM numbers(2000000);
INSERT INTO ch_lab.ts_dd    SELECT toDateTime64('2026-09-01 00:00:00',3) + interval number millisecond FROM numbers(2000000);

OPTIMIZE TABLE ch_lab.ts_lz4   FINAL;
OPTIMIZE TABLE ch_lab.ts_delta FINAL;
OPTIMIZE TABLE ch_lab.ts_dd    FINAL;

SELECT '--- A: three codecs, one timestamp column, 2M rows ---' AS step;
SELECT
    multiIf(table = 'ts_lz4',   '1. default (LZ4)',
            table = 'ts_delta', '2. Delta, ZSTD(1)',
                                '3. DoubleDelta, ZSTD(1)')          AS codec,
    formatReadableSize(sum(column_data_compressed_bytes))           AS on_disk,
    round(sum(column_data_uncompressed_bytes)
        / sum(column_data_compressed_bytes), 1)                     AS ratio
FROM system.parts_columns
WHERE database = 'ch_lab' AND table IN ('ts_lz4','ts_delta','ts_dd')
  AND column = 'ts' AND active
GROUP BY table ORDER BY codec;

-- Expected (approximately):
--   1. default (LZ4)          7.64 MiB
--   2. Delta, ZSTD(1)       755.55 KiB    ~10x vs LZ4
--   3. DoubleDelta, ZSTD(1)  18.90 KiB   ~414x vs LZ4, ~40x vs Delta
--
-- WHY: Delta stores v[i]-v[i-1]. Here that is a constant 1, so ZSTD sees
-- 2M identical 8-byte values -- compressible, but it still has to encode
-- them. DoubleDelta stores the change IN the delta, which for a constant
-- stride is a literal run of zeros. Pick Delta for timestamps that drift;
-- pick DoubleDelta for a fixed sampling interval. "Use Delta for
-- timestamps" is the folk rule, and on regular data it leaves 40x behind.

-- ---------------------------------------------------------------- Part B
DROP TABLE IF EXISTS ch_lab.codec_default;
DROP TABLE IF EXISTS ch_lab.codec_tuned;

CREATE TABLE ch_lab.codec_default
(
    ts  DateTime64(3),
    n   UInt32,
    txt String
)
ENGINE = MergeTree ORDER BY ts;

CREATE TABLE ch_lab.codec_tuned
(
    ts  DateTime64(3) CODEC(DoubleDelta, ZSTD(1)),  -- fixed 1 ms stride
    n   UInt32        CODEC(T64,         ZSTD(1)),  -- small ints: high bits all zero
    txt String        CODEC(ZSTD(6))                -- big repetitive text
)
ENGINE = MergeTree ORDER BY ts;

INSERT INTO ch_lab.codec_default
SELECT toDateTime64('2026-09-01 00:00:00', 3) + interval number millisecond,
       number % 1000,
       concat('status=ok region=eu-1 handler=checkout attempt=', toString(number % 7))
FROM numbers(2000000);

INSERT INTO ch_lab.codec_tuned
SELECT toDateTime64('2026-09-01 00:00:00', 3) + interval number millisecond,
       number % 1000,
       concat('status=ok region=eu-1 handler=checkout attempt=', toString(number % 7))
FROM numbers(2000000);

OPTIMIZE TABLE ch_lab.codec_default FINAL;
OPTIMIZE TABLE ch_lab.codec_tuned   FINAL;

SELECT '--- B: per column, default vs tuned ---' AS step;
-- NOTE: group on `column`, not `name` (`name` is the PART name here), and
-- sum column_data_compressed_bytes, not data_compressed_bytes (per-part).
SELECT
    column,
    formatReadableSize(sumIf(column_data_compressed_bytes, table = 'codec_default')) AS default_lz4,
    formatReadableSize(sumIf(column_data_compressed_bytes, table = 'codec_tuned'))   AS tuned,
    round(sumIf(column_data_compressed_bytes, table = 'codec_default')
        / sumIf(column_data_compressed_bytes, table = 'codec_tuned'), 1)             AS smaller_by
FROM system.parts_columns
WHERE database = 'ch_lab' AND table IN ('codec_default','codec_tuned') AND active
GROUP BY column
ORDER BY smaller_by DESC;

SELECT '--- B: whole table ---' AS step;
SELECT table, formatReadableSize(sum(data_compressed_bytes)) AS compressed
FROM system.parts
WHERE database = 'ch_lab' AND table IN ('codec_default','codec_tuned') AND active
GROUP BY table ORDER BY table;

-- Expected (Part B):
--   ts     7.64 MiB   -> 18.90 KiB   413.8x
--   txt  466.00 KiB   -> 44.48 KiB    10.5x
--   n    515.19 KiB   -> 138.89 KiB    3.7x
--   whole table 8.60 MiB -> 202.27 KiB  (~43x)
--
-- The timestamp is the column you filter and bucket by in every single
-- query, and it went from the largest column in the table to a rounding
-- error. That is a scan-bandwidth win, not just a disk win.
--
-- Reference table:
--   Delta,       ZSTD(1)   timestamps/counters that drift
--   DoubleDelta, ZSTD(1)   fixed-interval timestamps, monotonic counters
--   T64,         ZSTD(1)   small integers living in a wide int type
--   ZSTD(3..6)             large text rarely touched by aggregates
--   LowCardinality(String) bounded categoricals -- not a codec, same instinct
