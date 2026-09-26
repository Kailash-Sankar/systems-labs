"""Timed semantic search across all vector store backends."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from vector_search_lab.config import (
    DEFAULT_MODEL,
    MILVUS_URI,
    QDRANT_URL,
    REDIS_URL,
    milvus_collection_name,
    qdrant_collection_name,
    redis_index_name,
    redis_key_prefix,
    sqlite_db_path,
)
from vector_search_lab.embeddings import LocalEmbedder
from vector_search_lab.stores.base import SearchHit
from vector_search_lab.stores.milvus_store import MilvusStore
from vector_search_lab.stores.qdrant_store import QdrantStore
from vector_search_lab.stores.redis_store import RedisStore
from vector_search_lab.stores.sqlite_vec import SqliteVecStore

_embedder_cache: dict[str, LocalEmbedder] = {}


class Backend(str, Enum):
    sqlite = "sqlite"
    qdrant = "qdrant"
    redis = "redis"
    milvus = "milvus"


ALL_BACKENDS: tuple[Backend, ...] = (
    Backend.sqlite,
    Backend.qdrant,
    Backend.redis,
    Backend.milvus,
)


@dataclass(frozen=True)
class TimedSearchResult:
    backend: str
    hits: list[SearchHit] = field(default_factory=list)
    embed_ms: float = 0.0
    search_ms: float = 0.0
    total_ms: float = 0.0
    chunk_count: int = 0
    error: str | None = None


def get_embedder(model_key: str = DEFAULT_MODEL) -> LocalEmbedder:
    if model_key not in _embedder_cache:
        _embedder_cache[model_key] = LocalEmbedder(model_key)
    return _embedder_cache[model_key]


def _open_store(backend: Backend, *, model_key: str, dimensions: int) -> Any:
    if backend == Backend.sqlite:
        store = SqliteVecStore(sqlite_db_path(model_key), dimensions=dimensions)
    elif backend == Backend.qdrant:
        store = QdrantStore(
            url=QDRANT_URL,
            collection_name=qdrant_collection_name(model_key),
            dimensions=dimensions,
        )
    elif backend == Backend.redis:
        store = RedisStore(
            url=REDIS_URL,
            index_name=redis_index_name(model_key),
            key_prefix=redis_key_prefix(model_key),
            dimensions=dimensions,
        )
    else:
        store = MilvusStore(
            uri=MILVUS_URI,
            collection_name=milvus_collection_name(model_key),
            dimensions=dimensions,
        )
    store.connect()
    return store


def search_backend(
    backend: Backend,
    query: str,
    *,
    model_key: str = DEFAULT_MODEL,
    top_k: int = 5,
    source_path: str | None = None,
    query_vector: list[float] | None = None,
) -> TimedSearchResult:
    """Run embed + search on one backend; capture per-phase timing."""
    started = time.perf_counter()
    embed_ms = 0.0
    search_ms = 0.0
    store: Any | None = None

    try:
        embedder = get_embedder(model_key)
        if query_vector is None:
            t0 = time.perf_counter()
            query_vector = embedder.embed_query(query)
            embed_ms = (time.perf_counter() - t0) * 1000

        store = _open_store(backend, model_key=model_key, dimensions=embedder.dimensions)
        chunk_count = store.count()
        if chunk_count == 0:
            return TimedSearchResult(
                backend=backend.value,
                embed_ms=embed_ms,
                total_ms=(time.perf_counter() - started) * 1000,
                error=f"Index empty for {backend.value}. Run index.py --backend {backend.value}",
            )

        t1 = time.perf_counter()
        if source_path and backend != Backend.sqlite:
            hits = store.search(query_vector, top_k=top_k, source_path=source_path)
        else:
            hits = store.search(query_vector, top_k=top_k)
        search_ms = (time.perf_counter() - t1) * 1000

        return TimedSearchResult(
            backend=backend.value,
            hits=hits,
            embed_ms=embed_ms,
            search_ms=search_ms,
            total_ms=(time.perf_counter() - started) * 1000,
            chunk_count=chunk_count,
        )
    except Exception as exc:  # noqa: BLE001 — surface backend errors in UI/CLI
        return TimedSearchResult(
            backend=backend.value,
            embed_ms=embed_ms,
            search_ms=search_ms,
            total_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    finally:
        if store is not None:
            store.close()


def search_all_backends(
    query: str,
    *,
    model_key: str = DEFAULT_MODEL,
    top_k: int = 5,
    backends: tuple[Backend, ...] = ALL_BACKENDS,
    parallel: bool = True,
) -> list[TimedSearchResult]:
    """Search all backends; embed once, reuse vector across parallel searches."""
    embedder = get_embedder(model_key)
    t0 = time.perf_counter()
    query_vector = embedder.embed_query(query)
    shared_embed_ms = (time.perf_counter() - t0) * 1000

    results: list[TimedSearchResult] = []

    def run(backend: Backend) -> TimedSearchResult:
        result = search_backend(
            backend,
            query,
            model_key=model_key,
            top_k=top_k,
            query_vector=query_vector,
        )
        if result.embed_ms == 0.0:
            return TimedSearchResult(
                backend=result.backend,
                hits=result.hits,
                embed_ms=shared_embed_ms,
                search_ms=result.search_ms,
                total_ms=shared_embed_ms + result.search_ms,
                chunk_count=result.chunk_count,
                error=result.error,
            )
        return result

    if parallel and len(backends) > 1:
        with ThreadPoolExecutor(max_workers=len(backends)) as pool:
            futures = {pool.submit(run, b): b for b in backends}
            for future in as_completed(futures):
                results.append(future.result())
    else:
        for backend in backends:
            results.append(run(backend))

    order = {b.value: i for i, b in enumerate(backends)}
    results.sort(key=lambda r: order.get(r.backend, 99))
    return results
