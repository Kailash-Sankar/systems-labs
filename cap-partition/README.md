# cap-partition

Hands-on lab: run a counter across replicas, script network partitions, and measure CAP/PACELC tradeoffs.

Phased plan: [`docs/cap-partition-learning-plan.md`](docs/cap-partition-learning-plan.md) — all 7 phases complete.

The whole lab is one fixed scenario: 3 replicas, a 60s load run, node3 isolated
from t=20s to t=35s. Only the replication mode changes. CP shows up as an error
rate, AP as replica divergence — same script, opposite failure signal.

## Quick start

```bash
make sync

# Phase 1 — single-node baseline
make up NODES=1
make load DURATION=60

# Phase 2 — sync quorum, healthy network (W=2, R=2, N=3)
make up NODES=3 REPLICATION=sync
make load DURATION=60 NODES=3 REPLICATION=sync
make demo-quorum-loss                 # 2-of-3 still serves

# Phases 3/4 — same partition script, CP then AP
make load PARTITION=1 REPLICATION=sync
make load PARTITION=1 REPLICATION=ap

# Phase 6 — both runs on one chart
make compare-all
make plot-compare-partition
```

Copy `.env.sample` to `.env` for local overrides (never commit `.env`).
Run outputs land in `data/runs/` (gitignored).

## Makefile targets

| Target | Description |
|--------|-------------|
| `make sync` | Install Python deps with uv |
| `make up` | Start node(s) (`NODES=1` default, `NODES=3` → ports 8001–8003) |
| `make down` | Stop containers |
| `make load` | Run load test (`DURATION`, `CONCURRENCY`, `REPLICATION`, `PARTITION`) |
| `make partition-on` / `partition-off` | Isolate / restore node3 manually |
| `make stop-node NODE=3` | Stop one replica (quorum demo) |
| `make start-node NODE=3` | Start a stopped replica |
| `make demo-quorum-loss` | Scripted 2-of-3 survival demo |
| `make plot` | Chart a single run |
| `make compare-healthy` | Sync vs async on a healthy network (PACELC **E**) |
| `make compare-partition` | CP vs AP under the same partition (CAP **P**) |
| `make compare-all` | Both comparison sweeps |
| `make plot-compare-partition` | Side-by-side CP vs AP chart |
| `make logs` | Tail node logs |

## Replication modes

| Mode | Write path | Under partition |
|------|-----------|-----------------|
| `single` | Local only, no replication | N/A — baseline |
| `sync` | Quorum W=2 ACKs before returning | **CP** — minority side returns 503 |
| `async` | Local ACK, replicate in background | Fast + stale (PACELC **L**) |
| `ap` | Local write, local read, background push | **AP** — every island serves, values diverge |
