# CAP, PACELC & Quorums — Plan

Hands-on lab: run a single-key counter across three replicas, then **script a network partition** and measure the tradeoff you cannot avoid — reject operations (CP) vs serve conflicting values (AP). When the network is healthy, compare **sync quorum** vs **async replication** for the PACELC latency/consistency fork. Each phase is designed for its own session. Complete them in order.

---

## Context: Learning Exercise vs Production

| | This repo | Typical production |
|---|-----------|-------------------|
| Replicas | 3 FastAPI nodes in Docker Compose | Multi-AZ clusters, regional failover |
| Replication | Toy HTTP quorum or local-write modes | Raft (etcd, Consul), Paxos variants (Spanner), Dynamo-style quorums |
| Partition | `docker network disconnect` on one node | Real network splits, misconfigured security groups, AZ isolation |
| Merge on heal | Simple last-write-wins (LWW) by timestamp | Anti-entropy, CRDTs, operator runbooks |
| Goal | **Feel** CAP/PACELC tradeoffs with honest metrics | SLOs, consensus libraries, chaos engineering |

**Why three replicas from Phase 2:** A single node looks "CA" — both consistent and available — because partition never appears. Three nodes + an explicit split is the minimum setup where **W + R > N** and minority isolation both make sense.

**Why we do not implement Raft/Paxos:** Those are full consensus protocols (leader election, ordered log, safety proofs). This lab uses **quorum rules** and **local-write modes** that expose the same *client-visible* CP vs AP fork without a month of protocol engineering. Phase 7 names where Raft/Paxos sit in production.

Stop when the Phase 7 recap table (CAP under partition + PACELC on healthy network + quorum math) feels intuitive. Building Raft, CRDT deep dives, and multi-region failover are separate topics.

---

## Vocabulary

### CAP & PACELC

| Term | Plain meaning |
|------|---------------|
| **CAP theorem** | During a **network partition**, a distributed system cannot guarantee both **Consistency** and **Availability** at the same time — pick one. |
| **C (Consistency)** | Every successful read returns the value of the most recent successful write — as if there were a single copy (linearizable-ish). |
| **A (Availability)** | Every request to a **non-failing** node gets a **non-error** response (not guaranteed to be the latest value). |
| **Partition (P)** | Some nodes cannot talk to others; the cluster splits into islands that can still serve traffic locally. |
| **"CA" systems** | Not a third CAP choice under partition — means "partition has not happened" (e.g. single-node DB). Under **P**, you still choose C or A. |
| **PACELC** | Extends CAP: **If Partitioned** → choose **A** or **C**; **Else** (healthy network) → choose **Latency** or **Consistency**. |
| **L (Latency)** | Favor fast responses — often ACK after local write, replicate asynchronously, read from nearest/local replica. |
| **Split brain** | Two partitions both accepting writes independently; values diverge until merge or operator intervention. |

### Quorums & consistency models

| Term | Plain meaning |
|------|---------------|
| **N** | Total number of replicas in the replication group. |
| **W** | Write quorum — minimum replicas that must ACK a write before it is considered committed. |
| **R** | Read quorum — minimum replicas consulted (or required to agree) on a read. |
| **W + R > N** | Read and write sets overlap → a read after a successful write sees that write (the classic overlap rule). |
| **W > N/2** | Majority write quorum → at most one partition can commit writes (helps prevent dual-write split brain). |
| **Strong / linearizable** | Strongest client promise; what this lab's **CP** path approximates on the majority side. |
| **Eventual consistency** | Replicas converge if writes stop; reads may be stale or disagree in the meantime — **AP** path behavior under partition. |
| **Session consistency** | Read-my-writes + monotonic reads per client session — weaker than strong, better latency; not the focus of this lab. |

### Consensus algorithms (production CP — not implemented here)

| Term | Plain meaning |
|------|---------------|
| **Consensus** | Getting replicas to **agree on one ordered history** of operations despite crashes and delays. |
| **Paxos** | Classic consensus protocol (Lamport). Proposers/acceptors agree per "slot"; often extended to a replicated log. Used in Chubby and many academic/industrial variants. |
| **Raft** | Consensus protocol designed to be **easier to implement and teach** than Paxos. Leader + followers + replicated log. Used in **etcd**, **Consul**, CockroachDB-style stores. |
| **Relation to quorums** | Raft/Paxos **use** majority quorums internally; they add leader election, log ordering, and safety rules — quorums alone are not a full protocol. |
| **Relation to this lab** | Phase 3 **CP** ≈ "refuse without quorum" — the same *felt* guarantee Raft enforces with more machinery. |

---

## Concept map (how the pieces connect)

```
                    ┌─────────────────────────────────────┐
                    │   Consistency models (client view)   │
                    │   strong → session → eventual        │
                    └─────────────────┬───────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
   ┌──────▼──────┐             ┌───────▼───────┐           ┌───────▼───────┐
   │ CAP: under  │             │ PACELC: else  │           │ Mechanisms    │
   │ partition P │             │ healthy net E │           │               │
   │  A  or  C   │             │  L  or  C     │           │ quorums       │
   └──────┬──────┘             └───────┬───────┘           │ Raft / Paxos  │
          │                            │                   │ async + merge │
   Phase 3 │ Phase 4              Phase 2 │ Phase 2b       └───────────────┘
   (CP)   │ (AP)                 (sync)  │ (async)
```

---

## Fixed Demo Scenario (same for every phase)

Comparisons are only honest if inputs stay fixed.

| Knob | Value | Why |
|------|-------|-----|
| Key | `score` (single integer counter) | Easy to see divergence — not a subtle stale read |
| Replicas | 3 nodes (`node1`, `node2`, `node3`) | Minimum for majority quorum (2-of-3) |
| Quorum (CP / sync) | **N=3, W=2, R=2** | Standard teaching values; **W+R>N** holds |
| Load | 30 concurrent clients, ~50% read / 50% increment, **60 s** | Steady pressure through partition window |
| Client routing | Round-robin across all reachable nodes | Exposes minority vs majority behavior |
| Partition | **t=20s → t=35s** (15 s): isolate `node3` from `node1`+`node2` | Fixed, repeatable split |
| Partition inject | `scripts/partition.sh on\|off` via `docker network disconnect/connect` | Real network isolation, not just a flag |
| Simulated WAN RTT | ~50 ms between replicas (optional `tc` or sleep in RPC) | Makes sync vs async latency gap visible in Phase 2b |
| Primary metrics (partition phases) | `errors_during_partition`, `max_value_spread_during_partition` | CAP hurts as **errors** or **divergence**, not averages |
| Primary metrics (healthy Phase 2b) | `p99_write_ms`, `stale_read_count` | PACELC **E** fork: fast/stale vs slow/strong |

**Trigger events to watch:** partition start at t=20s, partition end at t=35s, post-heal convergence (Phase 5), one replica stopped in Phase 2 (quorum still works with 2 nodes).

---

## Write-up workflow (each phase)

Two write-ups, two jobs. This plan is the lab record; a separate personal
notes wiki (kept outside this repo) is the concept refresher.

| Where | Purpose |
|-------|---------|
| **This plan** (`docs/cap-partition-learning-plan.md`) | Measured numbers, status table, repo-specific commands |
| **Personal notes** (outside this repo) | Vocabulary, what clicked, recap tables; prose over raw metrics |

**After every phase session:**

1. Run the phase; fill the **Phase doc block** below in this plan (with measured results).
2. Carry the same block into the personal notes, stripped of repo-specific paths.
3. Add one **Takeaway** line under that block.
4. Tick the phase in the **Status** table at the bottom of this plan.

---

## Target Repo Layout

After all phases, `cap-partition/` should look like:

```
cap-partition/
├── docker-compose.yml          # 3 replica services + partition-capable network
├── Dockerfile
├── pyproject.toml              # uv, FastAPI, httpx
├── Makefile                    # up, down, load, partition, compare
├── .env.sample                 # N, W, R, REPLICATION, PARTITION_AT, etc.
├── data/runs/                  # JSON run artifacts (gitkeep; runs gitignored)
├── src/cap_partition/
│   ├── config.py               # quorum sizes, replication mode, RTT sleep
│   ├── metrics.py              # per-run counters, spread tracker, latency hist
│   ├── app.py                  # GET/POST /score, health, admin
│   ├── store.py                # in-memory value + version/timestamp
│   └── replication/
│       ├── base.py             # shared types, peer RPC helpers
│       ├── single.py           # Phase 1 — no replication
│       ├── sync_quorum.py      # Phase 2+ CP — W/R quorum over HTTP
│       ├── async_local.py      # Phase 2b / Phase 4 AP — local ACK, bg replicate
│       └── merge.py            # Phase 5 — LWW on heal (explicit, dumb on purpose)
├── scripts/
│   ├── loadgen.py              # concurrent clients, fixed 60s profile
│   ├── partition.sh            # docker network disconnect/connect node3
│   ├── plot_run.py             # timeline: errors, spread, optional latency
│   └── compare_runs.py         # side-by-side summary table
└── docs/
    └── cap-partition-learning-plan.md   # this file
```

---

## Open Decision — Phase 4 AP read path (review before implementing)

When partitions split the cluster and each side accepts local writes, what should **read** return?

| Approach | Behavior | Teaches | Downside |
|----------|----------|---------|----------|
| **A. Local value only** *(recommended)* | Each node returns its own `score` | Maximum divergence visibility; simple | Does not model "read quorum from local side" |
| **B. Side-local quorum** | Read requires R-of-N **within reachable peers only** | Closer to Dynamo tunable reads | Harder to implement; blurs pure AP |
| **C. Sticky client + monotonic** | Client pinned to one node | Session consistency tangent | Different lesson; save for a follow-up |

**Plan:** Implement **A (local value only)** in Phase 4. Keeps `max_value_spread` the honest metric.

---

## Open Decision — Phase 5 merge strategy (review before implementing)

| Approach | Behavior | Teaches |
|----------|----------|---------|
| **A. LWW by timestamp** *(recommended)* | On heal, each node pushes `(value, ts)`; keep max ts | Simple AP reconciliation; **not** safe for counters — call this out explicitly |
| **B. "Pick max value"** | Merge counter by `max(score)` | Wrong for general data but OK for demo counter | Misleading if you forget the caveats |
| **C. Operator freeze + manual** | Reject writes until admin picks winner | Real ops pattern | Too much scope |

**Plan:** Implement **A (LWW by timestamp)** and document in Phase 5: **counters need CRDTs or strong consistency — LWW is wrong for production counters; we use it to show merge exists, not to endorse it.**

---

## Phase 1 — Single Node Baseline

**Session goal:** Prove the read/increment loop and load script before replication or partitions.

**Duration:** ~30 min

### Stack
- One FastAPI service with in-memory `score`
- Endpoints: `GET /score`, `POST /score/increment`, `GET /health`
- Strategy: `REPLICATION=single`

### Tasks
1. `make sync` — install deps with uv
2. `make up NODES=1`
3. `make load DURATION=60` — saves JSON under `data/runs/`
4. Verify: zero errors, `max_value_spread=0`, final score ≈ increment count

### Concepts to learn

| Topic | Takeaway |
|-------|----------|
| Baseline | One node is always consistent and available — **until** you need scale or fault tolerance |
| "CA" | With no partition in the story, CAP does not force a choice — do not overclaim from Phase 1 |
| Load script | Same script reused in every phase — comparisons stay honest |

### Phase doc block (fill in after run)

```markdown
**What we tried:** Single in-memory counter, 30 workers, 60s, 50/50 read/increment.

**Example result:** ~30.7k requests (15.4k reads, 15.3k increments), 0 errors, max_value_spread=0, final score=15,315 (= increment count). p50 ~5 ms, p99 ~27 ms.

**What we learned:**
- Loop works; no divergence possible with one copy.
- This is the control run — every later phase uses the same load profile.
- One node looks "CA" because there is no partition — do not overclaim CAP from Phase 1.

**Takeaway:** A single-node DB never faces partition or multi-copy divergence; it is the baseline before distributed tradeoffs appear.
```

---

## Phase 2 — Sync Quorum Replication (Healthy Network)

**Session goal:** Three replicas, **W=2 / R=2 / N=3**; prove quorum math while the network is healthy.

**Duration:** ~45 min

### Pattern
1. **Write (increment):** propose to self → replicate to peers → commit when **W** ACKs (including self)
2. **Read:** fetch from peers → return value only when **R** matching responses agree (or max version among quorum)
3. Optional simulated **50 ms** inter-node delay on RPC — makes later async comparison meaningful

### Tasks
1. `make up NODES=3 REPLICATION=sync`
2. `make load DURATION=60` — no partition
3. `make stop-node NODE=3` mid-run or separate run — show **2-of-3 still serves** (quorum survives one failure)
4. Record: zero errors, zero spread, p99 write latency (baseline for Phase 2b)

### Concepts to learn

| Topic | Takeaway |
|-------|----------|
| **W + R > N** | With N=3, W=2, R=2: any read quorum overlaps any write quorum |
| **W > N/2** | Majority writes — at most one side of a future partition could commit |
| Healthy network | System looks "CA" again — **PACELC says the real fork here is L vs C**, not A vs C |
| vs Raft | We implement quorum ACK rules, not leader election — Raft adds ordering + safety on top |

### Phase doc block (fill in after run)

```markdown
**What we tried:** 3 nodes, sync quorum W=2 R=2, 60s load, no partition. Optional: node3 stopped.

**Example result:** Healthy run: ~1.6k ops (728 increments, 862 reads), 162 errors (503 under coordination load), final score 711 ≈ increment count, max_value_spread 3 (transient), all nodes converged. p99 write ~745 ms vs Phase 1 ~27 ms. Node3 stopped: 181 increments still served via 2-of-3 quorum.

**What we learned:**
- One node down, cluster still accepts reads/writes — quorum math in action.
- Writes pay coordination cost (multiple RPCs + 50 ms simulated RTT) — sets up Phase 2b latency comparison.
- W+R>N read path returns highest version among R responses; lagging replicas need catch-up push, not strict CAS only.

**Takeaway:** With N=3, W=2, R=2, losing one replica does not stop the cluster — but every write waits for cross-node ACKs, so latency jumps versus a single node.
```

---

## Phase 2b — PACELC "Else": Sync vs Async (Healthy Network)

**Session goal:** **No partition.** Compare **L** (async/local) vs **C** (sync quorum) on the same load script.

**Duration:** ~45 min

### Pattern — async mode (`REPLICATION=async`)
1. **Write:** increment locally → return **200 immediately** → background push to peers (best effort)
2. **Read:** return **local** value (may lag latest committed write on another node)
3. Track **stale reads:** read returned value lower than the global max version observed by loadgen oracle (or cross-check peers post-read)

### Tasks
1. `make load REPLICATION=sync` — record `p99_write_ms`, `stale_read_count` (expect ~0 stale)
2. `make load REPLICATION=async` — same 60s profile
3. `make compare-healthy` — table: sync vs async
4. Optional: `make plot` — latency histogram overlay

### Concepts to learn

| Topic | Takeaway |
|-------|----------|
| PACELC **E → L** | Async: lower write latency, accepts temporary staleness |
| PACELC **E → C** | Sync quorum: higher write latency, reads/writes strong within quorum rules |
| Not a partition tradeoff | Both modes can stay "available" — the fork is **latency vs consistency** |
| Real-world link | Dynamo/Cassandra tunable W/R; Spanner/Cockroach lean **C** in both P and E |

### Expected shape (illustrative — replace with measured)

| Mode | p99 write ms | stale_read_count (60s) | errors |
|------|--------------|------------------------|--------|
| sync | higher | ~0 | 0 |
| async | lower | >0 | 0 |

### Phase doc block (fill in after run)

```markdown
**What we tried:** Same 60s load, no partition. sync W=2 R=2 vs async local ACK.

**Example result:** sync: p99 write ~516 ms, 268 stale reads, 162 errors, spread 3. async: p99 write ~96 ms, 8567 stale reads, 0 errors, spread 10.

**What we learned:**
- Without partition, CAP is silent — PACELC's L vs C shows up in latency vs stale reads.
- "Available" does not mean "fast" — async is available **and** low-latency but weakly consistent.

**Takeaway:** When the network is healthy, you still choose latency or consistency — async ACKs locally in ~10 ms; sync quorum waits for peers and pays ~5× write latency to avoid stale reads.
```

---

## Phase 3 — Partition + CP (Consistency over Availability)

**Session goal:** Script the split; minority partition **rejects** ops it cannot quorum-commit; majority stays consistent.

**Duration:** ~45 min

### Pattern
- Same **sync quorum** as Phase 2
- On write/read: if fewer than **W** or **R** peers reachable → **503** (or 409) — do not serve guessed values
- `scripts/partition.sh on` at t=20s isolates `node3` from `{node1, node2}`

### Tasks
1. `make up NODES=3 REPLICATION=sync`
2. `make load PARTITION=1` — loadgen triggers partition at 20s (or orchestrator script)
3. `make plot` — vertical lines at partition start/end; chart **error rate** and **value spread**
4. Inspect: `errors_during_partition` **high on node3** (or clients hitting node3), **max_value_spread ≈ 0**

### Concepts to learn

| Topic | Takeaway |
|-------|----------|
| CAP **P → C** | Refuse rather than return stale or divergent data |
| Minority island | Cannot reach W=2 → cannot commit — **unavailable by design** |
| Majority island | Still has quorum → stays consistent **and** available to its clients |
| vs Raft | Production CP systems elect a leader on the majority side; minority stops accepting — same fork, more protocol |

### Phase doc block (fill in after run)

```markdown
**What we tried:** Sync quorum, partition node3 at t=20s for 15s.

**Example result:** 17 errors during partition (16 @ node3, 1 @ node1); spread during partition = 1 (no split-brain); majority kept serving. Error spike visible t=20–35s on chart.

**What we learned:**
- CP shows up as **errors**, not as wrong values.
- Clients on the minority side feel an outage; clients on the majority may notice nothing.
- This is why etcd/Consul "go read-only" or error on the minority partition.

**Takeaway:** Under partition, choosing consistency means the minority partition returns 503 rather than stale data — availability breaks on that side by design.
```

---

## Phase 4 — Partition + AP (Availability over Consistency)

**Session goal:** Same partition script; each island accepts **local writes** — measure **divergence**, not errors.

**Duration:** ~45 min

### Pattern
- `REPLICATION=async` or dedicated `local_writes` mode active **during partition**
- Writes always succeed locally on whichever node receives them
- Reads return local value (Open Decision A)
- Background replication to unreachable peers fails silently until heal

### Tasks
1. `make up NODES=3 REPLICATION=ap`
2. `make load PARTITION=1` — identical timing to Phase 3
3. Compare to Phase 3 on same chart axes: **errors ≈ 0**, **`max_value_spread` > 0** during partition
4. Note which clients saw which values — spread is the teaching artifact

### Concepts to learn

| Topic | Takeaway |
|-------|----------|
| CAP **P → A** | Respond on every non-crashed node — values **will** disagree |
| Split brain | Two islands both increment `score` independently |
| AP ≠ "always correct" | Availability here means **non-error response**, not fresh |
| Dynamo-style | Tunable quorums can drift AP/CP; this phase is deliberately pure AP |

### Phase doc block (fill in after run)

```markdown
**What we tried:** Local-write mode (ap), same partition window as Phase 3.

**Example result:** errors during partition ≈ 12 (transient @ node3); spread during partition = 6 vs sync = 1; max spread = 94. Both islands kept accepting writes.

**What we learned:**
- AP shows up as **conflicting reads**, not as 503s.
- Same load script, opposite failure shape from Phase 3 — that contrast is CAP.

**Takeaway:** Under partition, choosing availability means every island keeps returning 200 — values diverge, and you measure spread instead of error rate.
```

---

## Phase 5 — Heal and Reconcile

**Session goal:** Partition ends; watch **convergence** and the cost of dumb merge.

**Duration:** ~30 min

### Pattern
1. `partition.sh off` at t=35s — network heals
2. **CP path (sync):** node3 re-syncs from majority — should already match; measure `convergence_seconds ≈ 0`
3. **AP path:** run LWW merge (`merge.py`) — nodes exchange `(value, timestamp)`; converge to winner
4. Track `convergence_seconds` — time until all nodes report same `score`

### Tasks
1. Re-run Phase 4 load with partition + heal; record convergence time
2. Optional: compare CP heal (Phase 3 rerun, focus post-35s) vs AP heal
3. Document: **LWW loses increments** on counter — key caveat

### Concepts to learn

| Topic | Takeaway |
|-------|----------|
| Anti-entropy | Background sync after heal — production AP systems run repair jobs |
| LWW limits | Easy merge, **wrong for counters** — need CRDT (`PN-counter`) or strong consistency |
| CP heal | Minority catches up from majority log — Raft snapshot/ catch-up is the industrial version |
| Ops reality | Some teams **freeze writes** during ambiguous heal — out of scope but worth naming |

### Phase doc block (fill in after run)

```markdown
**What we tried:** AP partition run through heal; LWW merge enabled at t=35s. Also ran sync (CP) with catch-up sync for contrast.

**Example result:**

| | AP (LWW merge) | CP (catch-up sync) |
|--|----------------|---------------------|
| Spread at heal | 17 | 15 |
| Convergence after heal | ~0.06 s | ~0.03 s |
| Scores at heal | node1/2: 1577, node3: 1560 | node1/2: 225, node3: 210 |
| Scores at end | node1/2: 3204, node3: 3038 | all 446 |
| Max spread after heal | 160 | 20 (transient) |

**What we learned:**
- Divergence is temporary under AP, but merge policy matters.
- LWW converges fast but **loses the losing island's divergent increments** (~17 at heal).
- LWW is a teaching merge, not a counter fix — strong consistency or CRDTs for real counters.
- CP catch-up sync also heals in ~30 ms; quorum writes then keep all nodes aligned.
- AP without ongoing anti-entropy can **re-diverge** after a one-shot merge (node3 fell behind again post-heal).

**Takeaway:** After partition, AP systems need an explicit merge policy — LWW is easy but destroys counter increments; CP systems catch up from the majority log and stay aligned.
```

---

## Phase 6 — Side-by-Side: CP vs AP (Same Partition Script)

**Session goal:** One chart, two runs, fixed scenario — the CAP comparison you can sketch from memory.

**Duration:** ~30 min

### Tasks
1. `make load REPLICATION=sync PARTITION=1` — CP run
2. `make load REPLICATION=ap PARTITION=1` — AP run
3. `make compare-partition` — summary table + overlaid timeline plot
4. Fill comparison table below with **measured** numbers

### Partition comparison table (fill after runs)

| Mode | errors_during_partition | max_value_spread_during_partition | p99 during partition | Client experience |
|------|-------------------------|-----------------------------------|----------------------|-------------------|
| CP (sync quorum) | **20** | **2** | ~7247 ms | Minority returns 503; majority stays consistent |
| AP (local writes) | **9** | **6** | ~7018 ms* | Always 200 (mostly); stale/conflicting reads |

\* AP p99 during partition is inflated by stale-read detection timing out on the isolated node — not representative of write latency.

**Phase 6 takeaway:** Same partition, opposite signals — **errors vs spread** — that's CAP in one sentence.

Overlay chart: `data/runs/cp-vs-ap-partition.png`

### Phase doc block (fill in after run)

```markdown
**What we tried:** CP vs AP runs, same partition script; side-by-side compare + overlaid chart.

**Example result:** See comparison table above. CP: 20 errors, spread 2. AP: 9 errors, spread 6. Same 15s partition window, same load profile.

**What we learned:**
- Same partition, opposite failure shape — errors (CP) vs spread (AP).
- CP refuses on minority → clients see 503s; values stay aligned on majority.
- AP accepts everywhere → spread grows; clients always get 200 but may read stale/wrong values.
- One chart with both timelines makes the CAP fork visceral.

**Takeaway:** Same partition script, opposite failure signals — CP shows up as error rate, AP as replica spread; that's the CAP tradeoff in one comparison.
```

---

## Phase 7 — Full Recap: CAP + PACELC + Quorums + Consensus

**Session goal:** Consolidate; name where Raft/Paxos fit; stop line check.

**Duration:** ~30 min

### Tasks
1. Run `make compare-all` — healthy sync vs async **and** partition CP vs AP
2. Complete master recap table (below)
3. Read-aloud drill: explain each row without looking at code
4. **Finalize the personal notes** — merge the master recap table + takeaway sentences, and close with a **Takeaways** section
5. Optional: draft a blog primer from the notes + charts

### Master recap table

| Question | When | Choose | Lab phase | Metric (measured) |
|----------|------|--------|-----------|-------------------|
| Partition: consistency or availability? | **P** | **C** → reject without quorum | Phase 3 / 6 | `errors_during_partition` = **20** (sync) |
| Partition: consistency or availability? | **P** | **A** → local writes | Phase 4 / 6 | `max_value_spread_during_partition` = **6** (ap) |
| Healthy: latency or consistency? | **E** | **C** → sync W/R quorum | Phase 2b | p99 write **~516 ms**, stale reads **268** |
| Healthy: latency or consistency? | **E** | **L** → async local ACK | Phase 2b | p99 write **~96 ms**, stale reads **8567** |
| How many ACKs to write? | always | **W** of **N**; **W+R>N** | Phase 2 | survives 1 node loss (181 increments with node3 down) |
| Who implements CP in prod? | — | Raft / Paxos + majority | _(not built)_ | etcd, Consul, Spanner-family |

### Takeaways (check you can say these)

1. **CAP:** Under partition, I can optimize for consistent reads or for always getting a response — not both; our lab showed that as 503s vs divergent `score`.
2. **PACELC:** When the network is fine, I still trade write latency against staleness — sync quorum vs async replication on the same load.
3. **Quorum:** With N=3, W=2, R=2, one replica down still works; a minority partition cannot commit writes.
4. **Raft vs Paxos:** Both are consensus **algorithms** for a replicated log; Raft is easier to implement; quorums are necessary but not sufficient alone.
5. **LWW caveat:** Fine for demo merge; wrong for counters — use CRDT or CP.

### Stop line

Stop when you can whiteboard:

```
        [ Partition? ]
           /     \
         yes      no
         /          \
    A or C        L or C
   (Ph 3–4)      (Ph 2b)
```

…and point to **one metric** for each fork.

### Phase doc block (fill in after run)

```markdown
**What we tried:** `make compare-all` — healthy sync vs async + partition CP vs AP side-by-side.

**Example result:** Master recap table above filled with measured numbers from all phases.

**What we learned:**
- CAP only bites under partition (P); PACELC adds the healthy-network fork (E → L vs C).
- Quorums are necessary but not sufficient — Raft/Paxos add leader election + ordered log.
- Each fork has a concrete metric: errors, spread, p99 write, stale reads.

**Takeaway:** Whiteboard the decision tree (partition? → A/C; else → L/C) and name one metric per branch — that's the whole lab in one diagram.
```

---

## Makefile Targets (to implement)

```bash
make sync
make up [NODES=1|3] [REPLICATION=single|sync|async|ap]
make down
make load [DURATION=60] [REPLICATION=...] [PARTITION=0|1]
make partition-on          # isolate node3
make partition-off         # heal
make stop-node NODE=3      # Phase 2 quorum demo (stop container)
make plot                  # latest run timeline
make compare-healthy       # Phase 2b sync vs async
make compare-partition     # Phase 6 CP vs AP
make compare-all           # Phase 7 full recap
```

---

## Repo Checklist (before public push)

- [ ] `.env` gitignored; `.env.sample` has placeholders only
- [ ] No API keys or personal paths in tracked files
- [ ] `data/runs/*.json` gitignored; `data/runs/.gitkeep` committed
- [ ] README quick start in `cap-partition/README.md`
- [ ] `git add -A && git status` — confirm `.env` and run artifacts not staged

---

## Anti-Patterns

- Implementing Raft before Phase 3 shows **errors vs spread** on the toy quorum
- Using a fake "partition flag" only — real `docker network disconnect` at least from Phase 3 onward
- Measuring mean latency when the lesson is **error bursts** or **value spread**
- Claiming LWW merge "fixes" counters — call out data-model wrongness every time
- Comparing five replication modes before Phase 1 load loop is trusted
- Scope creep: multi-key, CRDTs, Kubernetes, Jepsen — all separate exercises

---

## Out of scope (explicit)

| Topic | Why |
|-------|-----|
| Raft / Paxos implementation | Full consensus is weeks; named in Phase 7 only |
| CRDTs (`PN-counter`) | Follow-up exercise after AP merge pain in Phase 5 |
| Session consistency / sticky routing | Different lesson; breaks fixed round-robin scenario |
| Multi-region / WAN partitions | Same concepts, harder infra |
| Jepsen / formal linearizability proofs | Overkill for weekend fundamentals |

---

## Status

| Phase | Status |
|-------|--------|
| 1 — Single node baseline | done |
| 2 — Sync quorum (healthy) | done |
| 2b — PACELC: sync vs async | done |
| 3 — Partition + CP | done |
| 4 — Partition + AP | done |
| 5 — Heal + merge | done |
| 6 — CP vs AP compare | done |
| 7 — Full recap | done |

---

## References (external)

- Brewer — CAP theorem (and later clarifications)
- Abadi — PACELC formulation
- Kleppmann — *Designing Data-Intensive Applications* (Ch. 5–9: replication, consistency, quorums)
- Ongaro & Ousterhout — Raft paper (readable consensus)
- Lamport — Paxos made simple
- Gilbert & Lynch — CAP formalization
