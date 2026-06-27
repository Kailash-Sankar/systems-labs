.PHONY: sync up down seed stampede stampede-bulk stampede-bulk-viz plot compare compare-bulk compare-bulk-viz logs

UV := UV_NO_CONFIG=1 uv

STRATEGY ?= naive
DURATION ?= 60
CONCURRENCY ?= 50
REPLICAS ?= 1
ITEM_COUNT ?= 100
RUN ?= $(shell ls -t data/runs/*.json 2>/dev/null | head -1)

ifeq ($(REPLICAS),3)
APP_SERVICES := app1 app2 app3
APP_URLS := http://localhost:8001,http://localhost:8002,http://localhost:8003
else
APP_SERVICES := app1
APP_URLS := http://localhost:8001
endif

sync:
	$(UV) sync --index-url https://pypi.org/simple

TTL_JITTER_PCT ?= 20
BULK_TAG ?=

up:
	CACHE_STRATEGY=$(STRATEGY) TTL_JITTER_PCT=$(TTL_JITTER_PCT) docker compose up -d --build redis $(APP_SERVICES)

down:
	docker compose down --remove-orphans

seed:
	mkdir -p data
	$(UV) run python scripts/seed_db.py --db data/app.db --count $(ITEM_COUNT)

stampede:
	$(UV) run python scripts/loadgen.py \
		--urls $(APP_URLS) \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--strategy $(STRATEGY) \
		--replicas $(REPLICAS) \
		--profile hot \
		--flush-cache \
		--output data/runs/$(STRATEGY)-r$(REPLICAS)-$$(date -u +%Y%m%d-%H%M%S).json

stampede-bulk:
	$(UV) run python scripts/loadgen.py \
		--urls $(APP_URLS) \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--strategy $(STRATEGY) \
		--replicas $(REPLICAS) \
		--profile bulk \
		--item-count $(ITEM_COUNT) \
		--warm-cache \
		--flush-cache \
		--output data/runs/$(STRATEGY)-bulk$(BULK_TAG)-r$(REPLICAS)-$$(date -u +%Y%m%d-%H%M%S).json

stampede-bulk-viz:
	$(MAKE) up REPLICAS=$(REPLICAS) STRATEGY=naive TTL_JITTER_PCT=20
	$(MAKE) stampede-bulk REPLICAS=$(REPLICAS) STRATEGY=naive ITEM_COUNT=$(ITEM_COUNT) BULK_TAG=-viz
	$(MAKE) up REPLICAS=$(REPLICAS) STRATEGY=jitter TTL_JITTER_PCT=100
	$(MAKE) stampede-bulk REPLICAS=$(REPLICAS) STRATEGY=jitter ITEM_COUNT=$(ITEM_COUNT) BULK_TAG=-viz

plot:
	@test -n "$(RUN)" || (echo "No run JSON in data/runs/. Run make stampede first." && exit 1)
	$(UV) run python scripts/plot_run.py $(RUN)

compare:
	$(UV) run python scripts/compare_runs.py --replicas $(REPLICAS) --profile hot

compare-bulk:
	$(UV) run python scripts/compare_runs.py --replicas $(REPLICAS) --profile bulk --strategies naive,jitter

compare-bulk-viz:
	$(UV) run python scripts/compare_runs.py --replicas $(REPLICAS) --profile bulk-viz --strategies naive,jitter

compare-all:
	@for s in naive jitter singleflight swr xfetch; do \
		$(MAKE) up REPLICAS=3 STRATEGY=$$s && $(MAKE) stampede REPLICAS=3 STRATEGY=$$s; \
	done
	$(MAKE) compare REPLICAS=3

logs:
	docker compose logs -f $(APP_SERVICES)
