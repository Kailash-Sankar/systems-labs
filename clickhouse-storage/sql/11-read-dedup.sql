-- EXP 11 — dedup at read time, the other option.
--
-- You can get one-row-per-key on a plain MergeTree without any engine
-- support. This is exactly what RMT does at merge time, hand-rolled per
-- query. The trade is WHERE THE KNOWLEDGE LIVES.

DROP TABLE IF EXISTS ch_lab.events;

CREATE TABLE ch_lab.events
(
    tenant_id  String,
    visit_id   String,
    event_id   String,
    amount     UInt32,
    updated_at DateTime
)
ENGINE = MergeTree                      -- plain, no version, no FINAL
ORDER BY (tenant_id, visit_id, event_id);

INSERT INTO ch_lab.events VALUES ('acme','v-1','ev-1',400,'2026-09-16 10:00:00');
INSERT INTO ch_lab.events VALUES ('acme','v-1','ev-1',950,'2026-09-16 10:05:00');
INSERT INTO ch_lab.events VALUES ('acme','v-1','ev-2',120,'2026-09-16 10:06:00');

SELECT '--- raw: the duplicate is there ---' AS step;
SELECT count() AS rows, sum(amount) AS total FROM ch_lab.events;

SELECT '--- LIMIT 1 BY: newest version of each event ---' AS step;
SELECT event_id, amount, updated_at
FROM ch_lab.events
WHERE tenant_id = 'acme' AND visit_id = 'v-1'
ORDER BY event_id, updated_at DESC
LIMIT 1 BY event_id;

SELECT '--- the same, aggregated ---' AS step;
SELECT count() AS rows, sum(amount) AS total
FROM (
    SELECT amount
    FROM ch_lab.events
    WHERE tenant_id = 'acme' AND visit_id = 'v-1'
    ORDER BY event_id, updated_at DESC
    LIMIT 1 BY event_id
);

SELECT '--- argMax: composes with aggregation, names every column ---' AS step;
SELECT count() AS rows, sum(latest) AS total
FROM (
    SELECT event_id, argMax(amount, updated_at) AS latest
    FROM ch_lab.events
    WHERE tenant_id = 'acme' AND visit_id = 'v-1'
    GROUP BY event_id
);

-- Expected: raw 3 / 1470; all three dedup forms 2 / 1070.
--
--                        FINAL (RMT)                LIMIT 1 BY (any engine)
--   knows the dedup key  the TABLE (its ORDER BY)   the QUERY (you type it)
--   knows the version    the table (engine arg)     the query (ORDER BY DESC)
--   cost driver          overlapping parts in range rows read
--   plain MergeTree      no                         yes
--   can use a projection never                      yes
--   storage shrinks      yes, merges drop losers    no, dupes live forever
--   if you forget it     wrong numbers, silently    wrong numbers, silently
--
-- FINAL is a table-level contract: correctness is centralised and every
-- reader inherits it -- but the contract binds all readers, including
-- those who wanted a projection. LIMIT 1 BY is a query-level opt-in: pay
-- only where needed, keep the table plain, but correctness becomes a
-- convention nobody enforces.
--
-- HEURISTIC: duplicates are an exception -> dedup in the query.
--            duplicates are the rule      -> dedup in the engine.
