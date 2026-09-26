.PHONY: sync index search compare up down qdrant-up index-qdrant search-qdrant redis-up index-redis search-redis milvus-up index-milvus search-milvus ui rag

# Global uv config points at JFrog; this lab uses public PyPI only.
UV := UV_NO_CONFIG=1 uv

sync:
	$(UV) sync --index-url https://pypi.org/simple

index:
	$(UV) run python scripts/index.py --model bge-small

search:
	$(UV) run python scripts/search.py $(Q)

compare:
	$(UV) run python scripts/compare_embeddings.py $(Q)

index-all:
	for m in minilm bge-small nomic; do $(UV) run python scripts/index.py --model $$m; done

qdrant-up:
	docker compose up -d qdrant

index-qdrant:
	$(UV) run python scripts/index.py --backend qdrant --model bge-small --rebuild

search-qdrant:
	$(UV) run python scripts/search.py --backend qdrant $(Q)

redis-up:
	docker compose up -d redis

index-redis:
	$(UV) run python scripts/index.py --backend redis --model bge-small --rebuild

search-redis:
	$(UV) run python scripts/search.py --backend redis $(Q)

milvus-up:
	docker compose up -d milvus

index-milvus:
	$(UV) run python scripts/index.py --backend milvus --model bge-small --rebuild

search-milvus:
	$(UV) run python scripts/search.py --backend milvus $(Q)

ui:
	$(UV) run uvicorn vector_search_lab.web.app:app --host 127.0.0.1 --port 8765

rag:
	$(UV) run python scripts/rag.py $(Q)

up:
	docker compose up -d

down:
	docker compose down
