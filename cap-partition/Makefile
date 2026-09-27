.PHONY: sync up down load logs stop-node start-node demo-quorum-loss compare-healthy compare-partition compare-all partition-on partition-off plot plot-compare-partition

UV := UV_NO_CONFIG=1 uv

NODES ?= 1
REPLICATION ?= single
DURATION ?= 60
CONCURRENCY ?= 30
PARTITION ?= 0
MERGE_ON_HEAL ?= 1
NODE ?= 3
RUN ?= $(shell ls -t data/runs/*partition*.json data/runs/sync-n3-p*.json 2>/dev/null | head -1)

ifeq ($(NODES),3)
NODE_SERVICES := node1 node2 node3
NODE_URLS := http://localhost:8001,http://localhost:8002,http://localhost:8003
PEERS := http://node1:8000,http://node2:8000,http://node3:8000
else
NODE_SERVICES := node1
NODE_URLS := http://localhost:8001
PEERS :=
endif

sync:
	$(UV) sync --index-url https://pypi.org/simple

up:
	REPLICATION=$(REPLICATION) PEERS=$(PEERS) docker compose up -d --build $(NODE_SERVICES)

down:
	docker compose down --remove-orphans

load:
	$(UV) run python scripts/loadgen.py \
		--urls $(NODE_URLS) \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--replication $(REPLICATION) \
		--nodes $(NODES) \
		--partition $(PARTITION) \
		--merge-on-heal $(MERGE_ON_HEAL) \
		--output data/runs/$(REPLICATION)-n$(NODES)$(if $(filter 1,$(PARTITION)),-partition,)-$$(date -u +%Y%m%d-%H%M%S).json

partition-on:
	bash scripts/partition.sh on

partition-off:
	bash scripts/partition.sh off

plot:
	@test -n "$(RUN)" || (echo "No partition run JSON in data/runs/. Run: make load PARTITION=1" && exit 1)
	$(UV) run python scripts/plot_run.py $(RUN)

stop-node:
	docker compose stop node$(NODE)

start-node:
	docker compose start node$(NODE)

demo-quorum-loss:
	$(MAKE) up NODES=3 REPLICATION=sync
	@echo "Stopping node3 to demonstrate 2-of-3 quorum..."
	docker compose stop node3
	$(MAKE) load DURATION=30 NODES=3 REPLICATION=sync
	docker compose start node3

compare-healthy:
	$(UV) run python scripts/compare_runs.py --nodes $(NODES) --modes sync,async

compare-partition:
	$(UV) run python scripts/compare_runs.py --nodes $(NODES) --modes sync,ap --partition
	$(UV) run python scripts/plot_compare_partition.py --nodes $(NODES)

plot-compare-partition:
	$(UV) run python scripts/plot_compare_partition.py --nodes $(NODES)

compare-all: compare-healthy compare-partition
	@echo ""
	@echo "=== Phase 7 recap ==="
	@echo "  Healthy (PACELC E):  sync p99 write vs async p99 write + stale reads"
	@echo "  Partition (CAP P):   sync errors vs ap spread during partition window"
	@echo "  Chart: data/runs/cp-vs-ap-partition.png"

logs:
	docker compose logs -f $(NODE_SERVICES)
