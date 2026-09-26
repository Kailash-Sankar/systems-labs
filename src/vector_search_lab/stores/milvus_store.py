"""Milvus vector store — Phase 5 billion-scale vector DB."""

from __future__ import annotations

from pymilvus import DataType, MilvusClient

from vector_search_lab.documents import Chunk
from vector_search_lab.stores.base import SearchHit

_OUTPUT_FIELDS = ("chunk_id", "source_path", "heading_path", "text")


def _escape_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class MilvusStore:
    """Store chunk vectors in a Milvus collection with scalar metadata fields."""

    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        dimensions: int,
    ) -> None:
        self.uri = uri
        self.collection_name = collection_name
        self.dimensions = dimensions
        self._client: MilvusClient | None = None

    def connect(self) -> MilvusClient:
        if self._client is None:
            self._client = MilvusClient(uri=self.uri)
        return self._client

    def close(self) -> None:
        self._client = None

    def __enter__(self) -> MilvusStore:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _collection_exists(self) -> bool:
        client = self.connect()
        return self.collection_name in client.list_collections()

    def _create_collection(self) -> None:
        client = self.connect()
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(
            field_name="vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=self.dimensions,
        )
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="source_path", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(
            field_name="heading_path",
            datatype=DataType.VARCHAR,
            max_length=1024,
        )
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="char_start", datatype=DataType.INT64)
        schema.add_field(field_name="char_end", datatype=DataType.INT64)

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )

        client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def init_schema(
        self,
        *,
        model_key: str,
        model_name: str,
        recreate: bool = False,
    ) -> None:
        del model_key, model_name
        if recreate and self._collection_exists():
            self.connect().drop_collection(self.collection_name)
        if not self._collection_exists():
            self._create_collection()

    def clear(self) -> None:
        client = self.connect()
        if self._collection_exists():
            client.drop_collection(self.collection_name)
        self._create_collection()

    def insert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )
        client = self.connect()
        rows: list[dict[str, object]] = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            if len(embedding) != self.dimensions:
                raise ValueError(
                    f"Expected {self.dimensions}-dim vector, got {len(embedding)}"
                )
            rows.append(
                {
                    "id": idx,
                    "vector": embedding,
                    "chunk_id": chunk.id,
                    "source_path": chunk.source_path,
                    "heading_path": chunk.heading_path,
                    "text": chunk.text,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                }
            )

        batch_size = 128
        for start in range(0, len(rows), batch_size):
            client.insert(
                collection_name=self.collection_name,
                data=rows[start : start + batch_size],
            )
        client.flush(self.collection_name)

    def count(self) -> int:
        if not self._collection_exists():
            return 0
        stats = self.connect().get_collection_stats(self.collection_name)
        return int(stats.get("row_count", 0))

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
        filter_expr: str | None = None
        if source_path is not None:
            safe = _escape_filter_value(source_path)
            filter_expr = f'source_path == "{safe}"'

        results = client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            limit=top_k,
            output_fields=list(_OUTPUT_FIELDS),
            filter=filter_expr,
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        )

        hits: list[SearchHit] = []
        for group in results:
            for hit in group:
                entity = hit.get("entity", {})
                # Milvus COSINE returns similarity (higher better) — convert to distance
                similarity = float(hit.get("distance", 0.0))
                distance = 1.0 - similarity
                hits.append(
                    SearchHit(
                        chunk_id=str(entity.get("chunk_id", "")),
                        source_path=str(entity.get("source_path", "")),
                        heading_path=str(entity.get("heading_path", "")),
                        text=str(entity.get("text", "")),
                        score=distance,
                    )
                )
        hits.sort(key=lambda h: h.score)
        return hits
