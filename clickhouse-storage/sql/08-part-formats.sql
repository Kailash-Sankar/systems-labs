-- EXP 8 — Compact vs Wide parts.
--
-- "One file per column per part" would mean a 60-column table producing
-- 60+ files on every tiny insert. ClickHouse avoids that with two part
-- formats, switched by a size threshold:
--
--   under min_bytes_for_wide_part -> Compact: all columns in one data.bin
--   over                          -> Wide:    one .bin + one .mrk per column
--
-- So the per-column file cost is only paid once a part is big enough to
-- earn it. "Millions of tiny files" needs the part count to run away first.

DROP TABLE IF EXISTS ch_lab.small_part;
DROP TABLE IF EXISTS ch_lab.big_part;

CREATE TABLE ch_lab.small_part
(
    id UInt64, a String, b String, c UInt32, d DateTime
)
ENGINE = MergeTree ORDER BY id;

CREATE TABLE ch_lab.big_part
(
    id UInt64, a String, b String, c UInt32, d DateTime
)
ENGINE = MergeTree ORDER BY id;

INSERT INTO ch_lab.small_part
SELECT number, 'aaaaaaaa', 'bbbbbbbb', rand() % 1000, now()
FROM numbers(100);

INSERT INTO ch_lab.big_part
SELECT number, randomPrintableASCII(40), randomPrintableASCII(40), rand() % 1000, now()
FROM numbers(1000000);

SELECT '--- the threshold ---' AS step;
SELECT name, value FROM system.merge_tree_settings WHERE name = 'min_bytes_for_wide_part';

SELECT '--- same schema, different part format ---' AS step;
SELECT table, part_type, rows, formatReadableSize(bytes_on_disk) AS size
FROM system.parts
WHERE database = 'ch_lab' AND table IN ('small_part','big_part') AND active
ORDER BY rows;

-- Expected:
--   min_bytes_for_wide_part = 10485760  (10 MB)
--   small_part  Compact      100  ~1.15 KiB
--   big_part    Wide     1000000  ~87 MiB
--
-- Count the files on disk to see the real difference (see the Makefile
-- target `make exp8-files`): Compact stays ~10 files however wide the
-- table gets; Wide scales with the column count.
