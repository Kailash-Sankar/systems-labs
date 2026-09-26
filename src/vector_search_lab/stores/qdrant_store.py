"""Qdrant vector store — Phase 3 dedicated vector DB."""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from vector_search_lab.documents import Chunk
from vector_search_lab.stores.base import SearchHit


class QdrantStore:
    """Store chunk vectors in a Qdrant collection with metadata payloads."""

    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        dimensions: int,
    ) -> None:
        self.url = url
        self.collection_name = collection_name
        self.dimensions = dimensions
        self._client: QdrantClient | None = None

    def connect(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(url=self.url)
        return self._client

    def close(self) -> None:
        self._client = None

    def __enter__(self) -> QdrantStore:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def init_schema(
        self,
        *,
        model_key: str,
        model_name: str,
        recreate: bool = False,
    ) -> None:
        client = self.connect()
        exists = client.collection_exists(self.collection_name)
        if exists and recreate:
            client.delete_collection(self.collection_name)
            exists = False
        if not exists:
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.dimensions,
                    distance=Distance.COSINE,
                ),
            )

    def clear(self) -> None:
        client = self.connect()
        if client.collection_exists(self.collection_name):
            client.delete_collection(self.collection_name)
        client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.dimensions,
                distance=Distance.COSINE,
            ),
        )

    def insert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )
        client = self.connect()
        points: list[PointStruct] = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            if len(embedding) != self.dimensions:
                raise ValueError(
                    f"Expected {self.dimensions}-dim vector, got {len(embedding)}"
                )
            points.append(
                PointStruct(
                    id=idx,
                    vector=embedding,
                    payload={
                        "chunk_id": chunk.id,
                        "source_path": chunk.source_path,
                        "heading_path": chunk.heading_path,
                        "text": chunk.text,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                    },
                )
            )

        batch_size = 128
        for start in range(0, len(points), batch_size):
            client.upsert(
                collection_name=self.collection_name,
                points=points[start : start + batch_size],
            )

    def count(self) -> int:
        client = self.connect()
        if not client.collection_exists(self.collection_name):
            return 0
        info = client.get_collection(self.collection_name)
        return int(info.points_count or 0)

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
        client = self.connect()
        query_filter: Filter | None = None
        if source_path is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source_path",
                        match=MatchValue(value=source_path),
                    )
                ]
            )

        response = client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )

        hits: list[SearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            # Qdrant cosine score = similarity (higher better); convert to distance for sqlite parity
            similarity = float(point.score or 0.0)
            distance = 1.0 - similarity
            hits.append(
                SearchHit(
                    chunk_id=str(payload.get("chunk_id", "")),
                    source_path=str(payload.get("source_path", "")),
                    heading_path=str(payload.get("heading_path", "")),
                    text=str(payload.get("text", "")),
                    score=distance,
                )
            )
        hits.sort(key=lambda h: h.score)
        return hits
