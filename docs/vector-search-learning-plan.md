# Vector Search Learning Lab — Plan

Hands-on lab indexing markdown notes into local vector stores. Each phase is designed for its own session. Complete them in order.

---

## Context: Learning Exercise vs Production RAG

| | This repo | Typical production |
|---|-----------|-------------------|
| Embeddings | Local FastEmbed (ONNX) | Hosted embedding API or batch pipeline |
| Vector store | sqlite-vec, Qdrant, Redis, Milvus on your machine | Managed vector DB, often multi-tenant |
| Goal | Understand chunk → embed → search → RAG | Ship search/RAG for users at scale |

This exercise uses a small **`corpus/`** folder in the repo (or your own path via `--corpus` / `CORPUS_PATH`) — real prose, local, small enough to iterate quickly.

**Corpus:** `corpus/` by default (~sample `.md` files). Override with `--corpus` or `CORPUS_PATH`.

**Repo:** clone `vector-search-lab` and run from repo root.

---

## Target Repo Layout

After all phases, `vector-search-lab/` should look like:

```
vector-search-lab/
├── docker-compose.yml              # Qdrant, Redis Stack, Milvus (Phases 3–5)
├── pyproject.toml                  # uv + FastEmbed + sqlite-vec + clients
├── src/vector_search_lab/
│   ├── config.py                   # corpus path, models, chunk sizes
│   ├── documents.py                # markdown load + heading-aware chunking
│   ├── embeddings.py               # LocalEmbedder (FastEmbed)
│   └── stores/
│       ├── base.py                 # SearchHit dataclass
│       ├── sqlite_vec.py           # Phase 1 backend
│       ├── qdrant_store.py         # Phase 3
│       ├── redis_store.py          # Phase 4
│       └── milvus_store.py         # Phase 5
├── scripts/
│   ├── index.py                    # typer CLI — chunk + embed + store
│   ├── search.py                   # typer CLI — semantic search
│   └── compare_embeddings.py       # side-by-side model comparison
├── data/                           # gitignored sqlite DBs per model
└── docs/
    └── vector-search-learning-plan.md   # this file
```

---

## Phase 1 — Embeddings + Chunking + sqlite-vec (No Docker)

**Session goal:** Understand the full retrieve path locally — text → chunks → vectors → cosine KNN.

**Duration:** ~45 min

### Tasks
1. Install deps: `cd vector-search-lab && uv sync`
2. Index the default corpus (`corpus/`):
   ```bash
   uv run python scripts/index.py --model bge-small
   ```
3. Search:
   ```bash
   uv run python scripts/search.py "clickhouse merge tree vs mysql"
   uv run python scripts/search.py "hexagonal architecture ports adapters" -k 3
   ```
4. Inspect the DB:
   ```bash
   sqlite3 data/corpus-bge-small.db "SELECT count(*) FROM chunks;"
   sqlite3 data/corpus-bge-small.db "SELECT chunk_id, substr(text,1,80) FROM chunks LIMIT 5;"
   ```

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| Embeddings | Fixed-size float vectors capturing semantic similarity — similar meaning → nearby in space |
| Chunking | Models have context limits; split docs by heading + sliding window so hits are readable |
| Cosine distance | Angle between vectors; 0 = identical direction. sqlite-vec `distance_metric=cosine` |
| vec0 virtual table | sqlite-vec KNN via `WHERE embedding MATCH ? AND k = N` — no separate server |
| Metadata join | vec0 stores vectors; regular `chunks` table holds text — join on `rowid` |

### Done when
- [ ] Index completes (sample corpus or your own `--corpus` path)
- [ ] Search returns relevant notes for 3 queries you invent
- [ ] You can explain chunking + cosine search in one paragraph

---

## Phase 2 — Compare 3 Local Embedding Models

**Session goal:** See how model choice changes retrieval — same corpus, same query, different rankings.

**Duration:** ~30 min

### Models (all via FastEmbed, no API keys)
| Key | Model | Dims | Notes |
|-----|-------|------|-------|
| `minilm` | `all-MiniLM-L6-v2` | 384 | Fast baseline |
| `bge-small` | `BAAI/bge-small-en-v1.5` | 384 | Strong retrieval; query/passage prefixes |
| `nomic` | `nomic-embed-text-v1.5` | 768 | Longer context; search_query/search_document prefixes |

### Tasks
1. Build all three indexes:
   ```bash
   for m in minilm bge-small nomic; do
     uv run python scripts/index.py --model $m
   done
   ```
2. Compare on the same queries:
   ```bash
   uv run python scripts/compare_embeddings.py "database replication leader follower"
   uv run python scripts/compare_embeddings.py "react performance re-render memo"
   ```
3. Note which model ranks your expected doc highest for 5 test queries

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| Model size vs quality | Smaller = faster; retrieval-tuned models beat general encoders |
| Query prefixes | BGE/nomic expect different strings for queries vs passages |
| Dimension mismatch | Each model needs its own DB — 384-dim query cannot search 768-dim index |
| MTEB / retrieval benchmarks | Useful starting point; your corpus is the real test |

### Done when
- [ ] Three DB files exist under `data/`
- [ ] Comparison table printed for 3+ queries
- [ ] You picked a default model for Phases 3–6 with a one-sentence rationale

---

## Phase 3 — Qdrant

**Session goal:** Move from embedded sqlite-vec to a dedicated vector database with collections and filtering.

**Duration:** ~45 min

### Tasks
1. Start Qdrant: `docker compose up -d qdrant`
2. Verify: `curl http://localhost:6333/readyz`
3. Implement `stores/qdrant_store.py` mirroring `SqliteVecStore` API
4. Index + search via Qdrant REST/gRPC client
5. Explore Qdrant dashboard at `http://localhost:6333/dashboard`

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| Collections | Named index with fixed vector size + distance metric |
| Payload | Arbitrary JSON metadata (source_path, heading) stored alongside vectors |
| HNSW index | Approximate nearest neighbor — fast at scale, tunable `ef` / `m` params |
| Filtering | Pre-filter by metadata (`source_path = 'Database/...'`) then vector search |

### Done when
- [ ] Qdrant container healthy
- [ ] Same corpus indexed in a `corpus_*` Qdrant collection
- [ ] Search returns equivalent top hits to sqlite-vec for 2 queries

---

## Phase 4 — Redis Stack (RediSearch Vectors)

**Session goal:** Learn vector search inside an in-memory data store — useful when you already run Redis.

**Duration:** ~45 min

### Tasks
1. Start Redis Stack: `docker compose up -d redis`
2. Verify: `redis-cli ping`
3. Implement `stores/redis_store.py` using RediSearch vector fields
4. Index hashes with `VECTOR` field (HNSW, COSINE)
5. Query with `FT.SEARCH ... =>[KNN 5 @embedding $vec AS score]`

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| RediSearch | Full-text + vector hybrid in one index |
| HASH vs JSON | Common pattern: HASH per chunk with text + vector blob |
| In-memory tradeoff | Fast, but RAM-bound — great for hot caches, not cold archives |
| Hybrid search | Combine BM25 text score + vector score (Phase 6 preview) |

### Done when
- [ ] Redis Stack running with vector index created
- [ ] KNN query returns indexed chunks
- [ ] You can explain when Redis vectors beat sqlite-vec vs Qdrant

---

## Phase 5 — Milvus

**Session goal:** Experience a vector-native DB designed for billion-scale collections.

**Duration:** ~45 min

### Tasks
1. Start Milvus standalone: `docker compose up -d milvus` (allow ~60s startup)
2. Verify: `curl http://localhost:9091/healthz`
3. Implement `stores/milvus_store.py` with `pymilvus`
4. Create collection, insert vectors + scalar fields, build index (IVF_FLAT or HNSW)
5. Search with `collection.search()`

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| Collections + partitions | Logical grouping; partitions for tenant or time sharding |
| Index types | FLAT (exact), IVF (inverted file clusters), HNSW — speed/recall tradeoffs |
| Consistency | Milvus supports stronger consistency models than pure ANN caches |
| When to use | Large corpora, multi-tenant SaaS, hybrid cloud vector pipelines |

### Done when
- [ ] Milvus healthy and collection loaded
- [ ] Search works for your indexed corpus
- [ ] You can compare Milvus vs Qdrant vs Redis in a table (ops, scale, filters)

---

## Phase 6 — RAG Mini-Pipeline

**Session goal:** Wire retrieval to generation — retrieve top-k chunks, prompt a local or API LLM.

**Duration:** ~60 min

### Tasks
1. Add `scripts/rag.py` (TODO): retrieve → assemble context → optional LLM answer
2. Retrieve with your best model from Phase 2
3. Build a prompt:
   ```
   Answer using only the context below. Cite source paths.
   Context: {top_k chunks}
   Question: {query}
   ```
4. Optional: run with Ollama (`llama3.2`) or skip LLM and print context-only "citation pack"
5. Measure: does the answer cite the right source file?

### Concepts to learn
| Topic | Takeaway |
|-------|----------|
| RAG | Retrieval-Augmented Generation — LLM grounded in fetched docs |
| Context window | Top-k × chunk_size must fit model limit; rerank or compress if not |
| Hallucination | Without good retrieval, LLM invents; cite sources in prompt |
| Reranking | Optional cross-encoder pass on top-20 → best-5 (future enhancement) |

### Done when
- [ ] Script prints retrieved context for a query
- [ ] Optional LLM step produces an answer citing `source_path`
- [ ] You tried one query where bad chunks → bad answer (intentional failure)

---

## Phase 7 — Write Up Your Learnings

**Session goal:** Consolidate what you learned — blog post, personal wiki, or internal doc.

**Duration:** ~30 min

### Tasks
1. Write a short note covering:
   - Embeddings intuition + cosine vs L2
   - Chunking strategies for markdown/technical docs
   - sqlite-vec vs Qdrant vs Redis vs Milvus — when to pick what
   - RAG pipeline sketch (retrieve → prompt → cite)
   - Model comparison results from Phase 2 (your actual queries)
2. Link from related notes if you keep a personal knowledge base

### Done when
- [x] Write-up exists with diagrams or tables
- [x] You can whiteboard vector search + RAG from memory

---

## Session Checklist (All Phases)

| Phase | Topic | Status |
|-------|-------|--------|
| 1 | Embeddings + chunking + sqlite-vec | ☑ |
| 2 | Compare minilm / bge-small / nomic | ☑ |
| 3 | Qdrant | ☑ |
| 4 | Redis Stack vectors | ☑ |
| 5 | Milvus | ☑ |
| 6 | RAG mini-pipeline | ☑ |
| 7 | Write-up / blog post | ☑ |

---

## Quick Reference

**Setup (Phase 1 — no Docker):**
```bash
cd vector-search-lab
uv sync
uv run python scripts/index.py --model bge-small
uv run python scripts/search.py "your query here"
```

**Compare models (Phase 2):**
```bash
for m in minilm bge-small nomic; do uv run python scripts/index.py --model $m; done
uv run python scripts/compare_embeddings.py "distributed systems cap theorem"
```

**Start vector DBs (Phases 3–5):**
```bash
docker compose up -d qdrant    # :6333
docker compose up -d redis      # :6380 (host) — Redis Stack with RediSearch
docker compose up -d milvus     # :19530 gRPC, :9091 health
docker compose ps
```

**Config knobs** (`src/vector_search_lab/config.py`):
| Setting | Default | Purpose |
|---------|---------|---------|
| `CORPUS_PATH` | `./corpus` | Markdown root to index |
| `CHUNK_SIZE` | 800 chars | Sliding window size |
| `CHUNK_OVERLAP` | 120 chars | Overlap between windows |
| `DEFAULT_MODEL` | `bge-small` | Default embedding model |
| `DEFAULT_TOP_K` | 5 | Results per query |

**Data files (gitignored):**
```
data/corpus-minilm.db
data/corpus-bge-small.db
data/corpus-nomic.db
```

---

## All phases complete

Optional follow-ups: cross-encoder reranking, hybrid BM25 + vector tuning, evaluation harnesses, larger corpus.
