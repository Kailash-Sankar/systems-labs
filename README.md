# vector-search-lab

Weekend learning exercise: local embeddings, vector search across four backends (sqlite-vec, Qdrant, Redis Stack, Milvus), and simple RAG via OpenRouter.

Write-up: see companion blog post in personal notes (`vector-search-and-rag-a-primer.md`).

## Quick start

Default corpus is [`corpus/`](corpus/) (a small sample note). Use your own markdown via `--corpus` or `CORPUS_PATH` in `.env`.

```bash
make sync
make index
make search Q='"clickhouse merge tree vs mysql"'
```

Your notes:

```bash
make index -- --corpus /path/to/your/notes
# or: export CORPUS_PATH=/path/to/your/notes && make index
```

## Backends

| Backend | Start | Index |
|---------|-------|-------|
| sqlite-vec | (default) | `make index` |
| Qdrant | `make qdrant-up` | `make index-qdrant` |
| Redis Stack | `make redis-up` | `make index-redis` |
| Milvus | `make milvus-up` | `make index-milvus` |

All Docker services: `make up` (Qdrant `:6333`, Redis `:6380`, Milvus `:19530`).

## RAG (optional)

Requires OpenRouter API key — copy `.env.sample` to `.env` (never commit `.env`):

```bash
cp .env.sample .env
make ui    # http://127.0.0.1:8765
make rag Q='"what is clickhouse column storage?"'
```

## Models

`minilm` (384d) · `bge-small` (384d, default) · `nomic` (768d) — compare with `make compare Q='"your query"'`.

Phased plan and deeper notes: [`docs/vector-search-learning-plan.md`](docs/vector-search-learning-plan.md).
