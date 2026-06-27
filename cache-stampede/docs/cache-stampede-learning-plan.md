# Cache Stampede & Thundering Herd — Plan

Hands-on lab: reproduce a cache expiry stampede against a slow origin DB, then fix it with Redis-backed strategies used in multi-instance deployments. Each phase is designed for its own session. Complete them in order.

---

## Context: Learning Exercise vs Production

| | This repo | Typical production |
|---|-----------|-------------------|
| Cache | Single local Redis (Docker) | Managed Redis / ElastiCache, often clustered |
| App tier | 2–3 FastAPI replicas via Compose | Many pods behind a load balancer |
| Origin DB | SQLite with intentional slow reads | Postgres/MySQL + connection pools |
| Goal | See stampede, measure it, compare fixes | SLOs, autoscaling, cache warming runbooks |

**Why Redis from Phase 1:** An in-process cache only protects one process. With multiple app replicas, a per-process mutex still allows **one stampede per pod**. Shared Redis makes expiry, locks, and stale values **global** — closer to how prod actually behaves.

Stop when the comparison table in Phase 6 feels intuitive. Redis Cluster, cache warming pipelines, and CDN edge cases are separate topics.

---

## Vocabulary

| Term | Plain meaning |
|------|---------------|
| **Thundering herd** | Many clients do the same expensive work at once (e.g. all hit the DB). |
| **Cache stampede** | Cache-specific herd: a hot key expires (or is cold) and every miss triggers an origin fetch for the **same** key. |
| **Single-flight / mutex** | For one key, only **one** refresher runs; others wait or use a fallback. |
| **Distributed lock** | Cross-process mutex via Redis `SET lock:{key} NX EX <ttl>` — only one pod wins. |
| **Stale-while-revalidate (SWR)** | Return **old** cached value immediately; refresh in the background. |
| **Probabilistic early expiration (XFetch)** | Before hard TTL, each read has a rising chance of triggering refresh — spreads load over time. |
| **TTL jitter** | Randomize expiry so keys written together don't all expire in the same millisecond. |

---

## Fixed Demo Scenario (same for every phase)

Comparisons are only honest if inputs stay fixed.

| Knob | Value | Why |
|------|-------|-----|
| Hot key | `item:1` (~95% of traffic) | Models one popular record |
| Cold keys | `item:2` … `item:10` (5% traffic) | Sanity check; not the focus |
| Cache TTL | 5 seconds | Re-triggers stampede often in a 60s run |
| DB read latency | ~200 ms (simulated) | Makes concurrent pile-up visible |
| Load | 50 concurrent clients, ~10 req/s each, 60 s | Sustained pressure across expiry boundaries |
| App replicas | 1 in Phase 1; **3 from Phase 2** | Multi-pod behavior |
| Primary metric | `max_db_queries_in_1s`, total DB queries | Stampede hurts in bursts, not averages |

**Trigger events to watch:** cold start (empty Redis), TTL expiry at t≈5,10,15…, optional `FLUSHDB` mid-run.

---

## Target Repo Layout

After all phases, `cache-stampede/` should look like:

```
cache-stampede/
├── docker-compose.yml          # redis + app (scalable replicas)
├── Dockerfile
├── pyproject.toml              # uv, FastAPI, redis-py
├── Makefile                    # up, down, stampede, compare
├── .env.sample
├── data/sample/                # seed SQLite (gitignored DB file)
├── src/cache_stampede/
│   ├── config.py               # REDIS_URL, TTL, DB_SLEEP_MS, STRATEGY
│   ├── db.py                   # slow origin read + query counter
│   ├── metrics.py              # db_queries, cache_hits, latencies
│   ├── app.py                  # GET /item/{id}
│   └── cache/
│       ├── base.py             # shared types + key naming
│       ├── naive.py            # GET / SETEX only
│       ├── jitter.py           # TTL jitter on SETEX
│       ├── singleflight.py     # distributed lock + wait/retry
│       ├── swr.py              # stale-while-revalidate
│       └── xfetch.py           # probabilistic early refresh
├── scripts/
│   ├── seed_db.py              # populate items table
│   └── loadgen.py              # concurrent clients, round-robin replicas
└── docs/
    └── cache-stampede-learning-plan.md   # this file
```

---

## Open Decision — Phase 3 Lock Losers (review before implementing)

When a request misses cache and **another pod already holds the refresh lock**, what should losers do?

| Approach | Behavior | Teaches | Downside |
|----------|----------|---------|----------|
| **A. Wait/retry** *(recommended for Phase 3)* | Sleep 25–50 ms, `GET` cache again, repeat until value appears or timeout | Real cost of **blocking** under lock; simple to implement | Higher p99 latency for unlucky requests |
| **B. Stale fallback** | If lock held, return previous value from Redis (even past soft TTL) | Smooth UX; bridges toward SWR | Blurs Phase 3 vs Phase 4 — harder to isolate "coordination" from "stale serving" |
| **C. Fail fast** | Return 503 / "try again" immediately | Useful in overload protection | Not a cache fix; different lesson |

**Plan:** Implement **A (wait/retry)** in Phase 3. Phase 4 introduces **B** properly as stale-while-revalidate with explicit soft/hard TTL fields.

> **Discuss during Phase 3 implementation:** Run the same load test with A only, then (optionally) a branch with B and compare p99 vs DB query count. Decide whether the wait cost or stale tolerance matters more for your mental model.

---

## Phase 1 — Naive Redis Cache + Reproduce the Stampede

**Session goal:** Prove the bug with shared Redis and a slow origin.

**Duration:** ~45 min

### Stack
- Docker Compose: `redis:7-alpine` + one `app` service (FastAPI)
- SQLite origin with ~200 ms simulated read
- Strategy: `GET item:{id}` → on miss, query DB → `SETEX item:{id} <ttl> <json>`

### Tasks
1. `make up` — Redis + one app replica
2. `make seed` — load sample items into SQLite
3. `make stampede STRATEGY=naive` — 60 s load test; saves JSON under `data/runs/`
4. `make plot` — chart DB queries/sec + latency (main teaching artifact)
5. Inspect summary table: total DB queries, `max_db_queries_in_1s`, p50/p99 latency
6. Optional: `redis-cli MONITOR` during test — watch repeated misses at expiry

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| Cache-aside | App owns read path: cache miss → load origin → populate cache |
| Expiry cliff | TTL turns a cache hit into a **scheduled incident** |
| Stampede shape | Not "high average QPS" — a **spike** of concurrent origin reads |

### Phase doc block (fill in after run)
```markdown
**What we tried:** Naive Redis cache-aside (`GET` → miss → 200ms SQLite read → `SETEX` 5s). One app replica, Redis flushed before test. 50 concurrent workers × 60s, 95% traffic to `item:1`.

**Example result:** 16,060 requests, 95.9% cache hit rate, but **659 total DB queries** and **63 DB queries in a single 1s window** at expiry. p50 49ms vs p99 587ms.

**What we learned:**
- High cache hit rate hides the problem — averages look fine while expiry causes burst damage.
- Stampede shows up in **max DB queries in 1s**, not mean latency alone.
- With 5s TTL over 60s (~12 expiry cycles), naive cache still produced hundreds of origin reads instead of ~12.
```

---

## Phase 2 — Multiple App Replicas (Still Naive)

**Session goal:** See why per-process fixes don't apply; stampede is global across pods.

**Duration:** ~30 min

### Tasks
1. Scale app: `make up REPLICAS=3` (ports 8001–8003)
2. Loadgen round-robins across replicas
3. Re-run `make stampede REPLICAS=3`
4. Compare to Phase 1: DB query count should be **worse or comparable**, not better

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| Shared cache | All replicas read/write the same key — expiry is global |
| No local mutex yet | Nothing coordinates **who** refreshes across pods |
| Load balancer | Clients spread across pods; problem is **coordination**, not client count |

### Phase doc block (fill in after run)
```markdown
**What we tried:** Same naive strategy, 3 replicas, round-robin loadgen. DB stats via Redis (global).

**Example result:** ~8.5k req/replica. 689 total DB queries, max 61/s — comparable to Phase 1 (664 / 63).

**What we learned:**
- More app instances did not reduce origin load.
- Each replica runs miss → DB → SETEX independently at expiry.
- Phase 3 needs distributed lock in Redis, not per-process mutex.
```

---

## Phase 3 — Distributed Single-Flight (Mutex Lock)

**Session goal:** Collapse N concurrent misses into **one** origin read across all replicas.

**Duration:** ~45 min

### Pattern
1. `GET item:{id}` — hit → return
2. Miss → `SET lock:item:{id} 1 NX EX 10` — winner refreshes from DB, `SETEX item:{id}`, `DEL lock`
3. Losers → **wait/retry** (see Open Decision above): backoff loop, re-`GET item:{id}` until populated or timeout

### Tasks
1. Implement `singleflight.py` with explicit metrics: `lock_waits`, `lock_timeouts`
2. `make up REPLICAS=3 STRATEGY=singleflight && make stampede REPLICAS=3 STRATEGY=singleflight`
3. Compare to Phase 2: `max_db_queries_in_1s` should drop to ~1 per expiry cycle
4. **Discussion checkpoint:** review wait/retry p99 vs Phase 2 stampede p99 — was blocking worth it?

### Phase doc block (fill in after run)
```markdown
**What we tried:** `SET lock:item:{id} NX EX 10` — winner refreshes; losers wait/retry (50ms backoff, 5s timeout). 3 replicas.

**Example result:** 111 total DB queries (vs 689 naive), max 8/s (vs 61/s). 623 wait_hit responses, 0 lock timeouts. p99 213ms (vs 216ms naive r3).

**What we learned:**
- Distributed lock collapses stampede: ~12 expiry cycles × ~1 refresh ≈ order-of-magnitude fewer DB reads.
- Losers pay wait cost (`wait_hit`) but p99 barely moved — most waits are shorter than one DB read (~200ms).
- Wait/retry was worth it here; Phase 4 SWR removes even that wait for users who tolerate stale data.
```

---

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| `SET NX EX` | Atomic "I am the refresher" — only one pod wins |
| Lock TTL | Prevents dead lock if refresher crashes mid-flight |
| Thundering herd fix | 100 misses → 1 DB query; others pay **wait** cost instead |
| vs in-process mutex | Must use Redis lock for multi-pod; `threading.Lock` is not enough |

### Honest failures to try
- Refresher slower than lock TTL — second winner may appear; tune `EX`
- Lock holder dies — lock expires, another stampede possible (brief)

---

## Phase 4 — Stale-While-Revalidate (SWR)

**Session goal:** Avoid user-visible waits; serve stale while one refresher updates.

**Duration:** ~45 min

### Pattern
Store in Redis (JSON or two keys):
- `value` — payload
- `soft_ttl` / `hard_ttl` (or single key with metadata)

On read:
- Before soft expiry → return fresh
- After soft, before hard → return stale **and** trigger background refresh (with lock)
- After hard → blocking refresh (fallback to Phase 3 behavior)

### Tasks
1. Implement `swr.py`
2. `make up REPLICAS=3 STRATEGY=swr && make stampede REPLICAS=3 STRATEGY=swr`
3. Compare p99 vs Phase 3 and DB query count (should be similar origin, better latency)

### Phase doc block (fill in after run)
```markdown
**What we tried:** Envelope with cached_at. Soft 5s / stale 5s / hard 10s. Background refresh on stale; blocking single-flight on cold miss.

**Example result:** 111 DB queries, max 7/s. 1160 stale, 50 wait_hit (vs 623 wait_hit single-flight). p99 28ms (vs 213ms).

**What we learned:**
- SWR is the UX layer; single-flight is the origin-protection layer — compose both.
- Expiry cliff becomes "serve stale + refresh" instead of "everyone waits or misses."
```

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| SWR | HTTP `Cache-Control: stale-while-revalidate` in app logic |
| UX vs consistency | Users see fast stale data; freshness bounded by hard TTL |
| Background refresh | Lock + single-flight still applies — SWR doesn't remove coordination |

---

## Phase 5 — Probabilistic Early Expiration (XFetch)

**Session goal:** Spread refresh load **before** the hard expiry cliff.

**Duration:** ~45 min

### Pattern (simplified XFetch)
On each read when key exists:
1. Read remaining TTL (`TTL key`)
2. Compute refresh probability increasing as TTL → 0 (e.g. based on `beta` parameter)
3. If probabilistic refresh triggers → single-flight refresh **before** key goes cold

Reference: *Optimal Probabilistic Cache Stampede Prevention* (Vattani et al.) — implement a simplified version; exact optimality is not the goal.

### Tasks
1. Implement `xfetch.py` with tunable `XFETCH_BETA` in `.env.sample`
2. `make up REPLICAS=3 STRATEGY=xfetch && make stampede REPLICAS=3 STRATEGY=xfetch`
3. Compare spike metric vs Phase 3/4; note higher total DB count

### Phase doc block (fill in after run)
```markdown
**What we tried:** XFetch probability rises as age → TTL. Background single-flight refresh. beta=1.0.

**Example result:** 174 DB queries (vs 111 SWR), max 10/s. 6275 early_refresh. p99 21ms.

**What we learned:**
- Proactive refresh avoids empty-cache cliff; pays with more origin reads spread over time.
- beta tunes the spread vs freshness tradeoff.
```

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| Proactive refresh | Avoid the cliff instead of reacting to miss |
| Extra DB work | More **total** queries, fewer **spikes** — a tradeoff |
| Low traffic keys | Probability may rarely fire; behaves like naive until unlucky |

---

## Phase 6 — TTL Jitter + Side-by-Side Comparison

**Session goal:** Consolidate; jitter as partial fix; final comparison table.

**Duration:** ~30 min

### Tasks
1. Implement `jitter.py` — `SETEX` with `ttl + random(0, jitter_pct)`
2. Run **all strategies** with identical load script; fill comparison table
3. Update wiki note in dev-notes (personal) with findings

### Final comparison (measured, r3, 60s load)

| Strategy | max DB QPS (1s) | total DB queries (60s) | p99 ms | Complexity | Best when |
|----------|-----------------|------------------------|--------|------------|-----------|
| naive | 61 | 689 | 223 | low | never at scale |
| jitter | 57 | 616 | 218 | low | many keys expiring together after deploy |
| singleflight | 8 | 111 | 213 | medium | must minimize origin load |
| swr | 7 | 111 | 28 | medium | stale OK, latency sensitive |
| xfetch | 10 | 174 | 21 | medium | hot keys, smooth load |

**Phase 6 takeaway:** jitter barely moved the needle on our hot-key scenario — max DB/s still ~57 vs naive 61. Coordination (single-flight/SWR) or proactive refresh (XFetch) is what flattened spikes.

---

## Phase 7 — Bulk warm: jitter's home turf

**Session goal:** Show jitter helping when many keys expire together — contrast with Phase 6 hot-key result.

**Duration:** ~45 min

### Setup
1. `make seed ITEM_COUNT=100`
2. `POST /admin/warm-cache?count=100` — all keys written in one burst (simulates deploy warm)
3. Loadgen `--profile bulk` — even traffic across items 1–100
4. Compare **naive vs jitter** only (`make compare-bulk`)

### Measured (r1, 60s, 50 concurrent, 100 items warmed)

| Strategy | max DB/s | total DB | spike seconds (>50/s) | p99 ms |
|----------|----------|----------|----------------------|--------|
| naive | 92 | 1852 | 17 | 291 |
| jitter | 83 | 1749 | 11 | 237 |

### Takeaway
Jitter smears the first expiry cliff (naive 88/s at t=4 → jitter 66+73 across t=4–5) and reduces recurring spike seconds. Same code that barely helped on hot-key (Phase 6) — **scenario matters**.

### Makefile
```bash
make stampede-bulk STRATEGY=naive ITEM_COUNT=100
make stampede-bulk STRATEGY=jitter ITEM_COUNT=100
make compare-bulk REPLICAS=1

# Phase 7b — wide jitter for chart visualization (TTL_JITTER_PCT=100)
make stampede-bulk-viz REPLICAS=1 ITEM_COUNT=100
make compare-bulk-viz REPLICAS=1
```

### Phase 7b — wide jitter (viz)

Same bulk warm flow; jitter app runs with `TTL_JITTER_PCT=100` (5–10s TTL spread).

| Strategy | max DB/s | total DB | p99 ms |
|----------|----------|----------|--------|
| naive | 95 | 1891 | 289 |
| jitter (100% pct) | 45 | 1327 | 212 |

Use for charts/teaching. Phase 7 (20% pct) stays the realistic baseline.

---

## Makefile Targets (to implement)

```bash
make up [REPLICAS=1]     # docker compose up
make down
make seed [ITEM_COUNT=100]
make stampede            # hot-key profile (95% item:1)
make stampede-bulk       # bulk profile + warm-cache (Phase 7)
make compare             # hot-key runs
make compare-bulk        # naive vs jitter bulk runs
```

---

## Repo Checklist (before public push)

- [ ] `.env` gitignored; `.env.sample` has placeholders only
- [ ] No API keys or personal paths in tracked files
- [ ] Sample data under `data/sample/`; generated `.db` gitignored
- [ ] README quick start in `cache-stampede/README.md`
- [ ] `git add -A && git status` — confirm `.env` and `data/*.db` not staged

---

## Anti-Patterns

- Turning up concurrency before a single naive miss → refresh → hit loop works
- Benchmarking five strategies before Phase 1 shows a visible expiry spike
- Using in-process cache "for simplicity" then claiming multi-pod fixes work
- Skipping the Phase 3 discussion checkpoint — wait/retry vs stale is the core design fork
- Writing the blog before the wiki note (wiki holds truth; blog distills)

---

## Status

| Phase | Status |
|-------|--------|
| 1 — Naive stampede | done |
| 2 — Multi-replica naive | done |
| 3 — Single-flight (wait/retry) | done |
| 4 — SWR | done |
| 5 — XFetch | done |
| 6 — Jitter + compare | done |
| 7 — Bulk warm (jitter demo) | done |

---

## References (external)

- Vattani et al. — probabilistic early expiration (XFetch)
- Redis docs: `SET key value NX EX`, `TTL`
- HTTP caching: `stale-while-revalidate` (MDN / RFC 5861)
