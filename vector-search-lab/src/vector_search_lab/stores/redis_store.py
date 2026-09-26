"""Redis Stack (RediSearch) vector store — Phase 4 in-memory KNN."""

from __future__ import annotations

import struct
from typing import Any

import redis
from redis.commands.search.field import NumericField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.exceptions import ResponseError

from vector_search_lab.documents import Chunk
from vector_search_lab.stores.base import SearchHit

_VECTOR_ATTRS = {
    "TYPE": "FLOAT32",
    "DISTANCE_METRIC": "COSINE",
}


def _vector_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _escape_text(value: str) -> str:
    """Escape double quotes for RediSearch TEXT exact-match queries."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


class RedisStore:
    """Store chunk vectors in Redis HASH documents with a RediSearch HNSW index."""

    def __init__(
        self,
        *,
        url: str,
        index_name: str,
        key_prefix: str,
        dimensions: int,
    ) -> None:
        self.url = url
        self.index_name = index_name
        self.key_prefix = key_prefix
        self.dimensions = dimensions
        self._client: redis.Redis | None = None

    def connect(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self.url, decode_responses=False)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> RedisStore:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _search_index(self) -> Any:
        return self.connect().ft(self.index_name)

    def _schema(self) -> tuple[Any, ...]:
        attrs = {**_VECTOR_ATTRS, "DIM": self.dimensions}
        return (
            TextField("chunk_id"),
            TextField("source_path"),
            TextField("heading_path"),
            TextField("text"),
            NumericField("char_start"),
            NumericField("char_end"),
            VectorField("embedding", "HNSW", attrs),
        )

    def init_schema(
        self,
        *,
        model_key: str,
        model_name: str,
        recreate: bool = False,
    ) -> None:
        del model_key, model_name  # stored in index/key naming only for this backend
        client = self.connect()
        if recreate:
            self._drop_index_if_exists()
        try:
            self._search_index().info()
        except ResponseError:
            definition = IndexDefinition(prefix=[self.key_prefix], index_type=IndexType.HASH)
            self._search_index().create_index(self._schema(), definition=definition)

    def _drop_index_if_exists(self) -> None:
        try:
            self._search_index().dropindex(delete_documents=True)
        except ResponseError:
            pass

    def clear(self) -> None:
        self._drop_index_if_exists()
        definition = IndexDefinition(prefix=[self.key_prefix], index_type=IndexType.HASH)
        self._search_index().create_index(self._schema(), definition=definition)

    def insert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )
        client = self.connect()
        pipe = client.pipeline(transaction=False)
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            if len(embedding) != self.dimensions:
                raise ValueError(
                    f"Expected {self.dimensions}-dim vector, got {len(embedding)}"
                )
            key = f"{self.key_prefix}{idx}".encode()
            mapping = {
                b"chunk_id": chunk.id.encode(),
                b"source_path": chunk.source_path.encode(),
                b"heading_path": chunk.heading_path.encode(),
                b"text": chunk.text.encode(),
                b"char_start": str(chunk.char_start).encode(),
                b"char_end": str(chunk.char_end).encode(),
                b"embedding": _vector_to_bytes(embedding),
            }
            pipe.hset(key, mapping=mapping)
        pipe.execute()

    def count(self) -> int:
        try:
            info = self._search_index().info()
        except ResponseError:
            return 0
        return int(info.get("num_docs", 0))

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        source_path: str | None = None,
    ) -> list[SearchHit]:
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query vector has {len(query_vector)} dims, expected {self.dimensions}"
            )
        if source_path:
            safe_path = _escape_text(source_path)
            query_str = (
                f'@source_path:"{safe_path}"=>[KNN {top_k} @embedding $vec AS score]'
            )
        else:
            query_str = f"*=>[KNN {top_k} @embedding $vec AS score]"

        # redis-py 8 returns FT.SEARCH as a dict; Query().search() no longer yields docs.
        raw = self.connect().execute_command(
            "FT.SEARCH",
            self.index_name,
            query_str,
            "PARAMS",
            2,
            "vec",
            _vector_to_bytes(query_vector),
            "RETURN",
            5,
            "chunk_id",
            "source_path",
            "heading_path",
            "text",
            "score",
            "SORTBY",
            "score",
            "DIALECT",
            2,
        )

        hits: list[SearchHit] = []
        for row in _parse_search_results(raw):
            hits.append(
                SearchHit(
                    chunk_id=row.get("chunk_id", ""),
                    source_path=row.get("source_path", ""),
                    heading_path=row.get("heading_path", ""),
                    text=row.get("text", ""),
                    score=float(row.get("score", "0")),
                )
            )
        hits.sort(key=lambda h: h.score)
        return hits


def _parse_search_results(raw: object) -> list[dict[str, str]]:
    """Parse redis-py 8 FT.SEARCH dict response into flat field dicts."""
    if not isinstance(raw, dict):
        return []
    rows = raw.get("results") or raw.get(b"results") or []
    parsed: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("extra_attributes") or row.get(b"extra_attributes") or {}
        if not isinstance(attrs, dict):
            continue
        parsed.append({ _decode_field(k): _decode_field(v) for k, v in attrs.items() })
    return parsed


def _decode_field(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)
