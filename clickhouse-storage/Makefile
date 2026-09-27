SHELL := /bin/bash
CONTAINER ?= ch-storage-lab
CH = docker exec -i $(CONTAINER) clickhouse-client
RUNS = data/runs
STAMP = $(shell date +%Y%m%d-%H%M%S)

# Run one sql/ file through the client, pretty-printed.
define run_sql
@$(CH) --multiquery --format PrettyCompactMonoBlock < sql/$(1)
endef

.PHONY: help up down logs shell wait reset \
        exp1 exp2 exp3 exp4 exp5 exp6 exp7 exp8 exp8-files exp9 exp10 exp11 exp12 \
        all capture clean

help:
	@echo "ClickHouse storage lab"
	@echo ""
	@echo "  make up          start the server (HTTP 8124, native 9001)"
	@echo "  make down        stop it"
	@echo "  make reset       drop and recreate the ch_lab database"
	@echo "  make shell       interactive clickhouse-client"
	@echo ""
	@echo "  make all         run every experiment in order"
	@echo "  make capture     run every experiment, tee to $(RUNS)/"
	@echo ""
	@echo "  Phase 1  exp1   one insert = one part; MT vs RMT before merge"
	@echo "  Phase 2  exp2   the same tables after a merge runs"
	@echo "           exp3   FINAL on a plain MergeTree is illegal"
	@echo "           exp11  dedup at read time (LIMIT 1 BY / argMax)"
	@echo "  Phase 3  exp4   mutable column in the dedup key -> permanent dupes"
	@echo "           exp5   merges never cross a partition"
	@echo "  Phase 4  exp6   async_insert coalesces 8 inserts into 1 part"
	@echo "  Phase 5  exp7   256 parts collapse geometrically"
	@echo "           exp8   Compact vs Wide parts   (exp8-files counts files)"
	@echo "  Phase 6  exp9   codecs: 414x on a fixed-stride timestamp column"
	@echo "  Phase 7  exp10  projections: 122x fewer rows read"
	@echo "           exp12  projection on an RMT is rejected outright"

up:
	docker compose up -d
	@$(MAKE) --no-print-directory wait
	@$(MAKE) --no-print-directory reset
	@echo "ready. HTTP :8124  native :9001"

down:
	docker compose down

logs:
	docker compose logs -f ch

shell:
	@docker exec -it $(CONTAINER) clickhouse-client --database ch_lab

wait:
	@echo -n "waiting for clickhouse"
	@for i in {1..40}; do \
		if $(CH) --query "SELECT 1" >/dev/null 2>&1; then echo " ok"; exit 0; fi; \
		echo -n "."; sleep 1; \
	done; echo " timed out"; exit 1

reset:
	$(call run_sql,00-reset.sql)

exp1:  ; $(call run_sql,01-mt-vs-rmt.sql)
exp2:  ; $(call run_sql,02-after-merge.sql)
exp4:  ; $(call run_sql,04-mutable-key.sql)
exp5:  ; $(call run_sql,05-cross-partition.sql)
exp8:  ; $(call run_sql,08-part-formats.sql)
exp9:  ; $(call run_sql,09-codecs.sql)
exp10: ; $(call run_sql,10-projections.sql)
exp11: ; $(call run_sql,11-read-dedup.sql)

# Expected to fail with Code: 181 ILLEGAL_FINAL -- that IS the result.
exp3:
	@echo "--- expecting Code: 181 ILLEGAL_FINAL ---"
	-@$(CH) --multiquery < sql/03-illegal-final.sql

# Expected to fail with Code: 344 SUPPORT_IS_DISABLED -- that IS the result.
exp12:
	@echo "--- expecting Code: 344 SUPPORT_IS_DISABLED ---"
	-@$(CH) --multiquery --format PrettyCompactMonoBlock < sql/12-projection-on-rmt.sql

exp6:  ; @./scripts/exp06_async_insert.sh
exp7:  ; @./scripts/exp07_merge_cascade.sh

# Count real files on disk for a Compact vs a Wide part.
exp8-files:
	@for t in small_part big_part; do \
		d=$$($(CH) --query "SELECT path FROM system.parts WHERE database='ch_lab' AND table='$$t' AND active LIMIT 1"); \
		n=$$(docker exec $(CONTAINER) sh -c "ls -1 $$d | wc -l"); \
		echo "$$t -> $$n files in the part dir"; \
	done

all: reset exp1 exp2 exp3 exp11 exp4 exp5 exp6 exp7 exp8 exp8-files exp9 exp10 exp12
	@echo ""
	@echo "all experiments done."

capture:
	@mkdir -p $(RUNS)
	@$(MAKE) --no-print-directory all 2>&1 | tee $(RUNS)/run-$(STAMP).txt
	@echo "saved -> $(RUNS)/run-$(STAMP).txt"

clean:
	docker compose down -v
