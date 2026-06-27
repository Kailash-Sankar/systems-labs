# cache-stampede

Weekend learning exercise: reproduce cache stampede / thundering herd with shared Redis, then compare fixes.

Phased plan: [`docs/cache-stampede-learning-plan.md`](docs/cache-stampede-learning-plan.md)

## Quick start (Phase 1–2)

```bash
make sync
make seed
make up                  # 1 replica (app1 on :8001)
make up REPLICAS=3       # 3 replicas (:8001–:8003)
make stampede            # 1 replica
make stampede REPLICAS=3 STRATEGY=singleflight  # Phase 3
make stampede REPLICAS=3 STRATEGY=swr           # Phase 4
make stampede REPLICAS=3 STRATEGY=xfetch        # Phase 5
make plot
```

Optional: watch Redis during the run:

```bash
docker compose exec redis redis-cli MONITOR
```

## Makefile targets

| Target | Description |
|--------|-------------|
| `make sync` | Install Python deps with uv |
| `make seed` | Create `data/app.db` with sample items |
| `make up` | Start Redis + app (`REPLICAS=1` default, `REPLICAS=3` → ports 8001–8003) |
| `make down` | Stop containers |
| `make stampede` | Run load test (`REPLICAS`, `DURATION`, `CONCURRENCY`) |
| `make plot` | Chart latest run JSON |
| `make logs` | Tail app logs |

Copy `.env.sample` to `.env` for local overrides (never commit `.env`).
