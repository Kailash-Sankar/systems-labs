"""sqlite-vec store: vec0 virtual table with cosine distance."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec
from sqlite_vec import serialize_float32

from vector_search_lab.documents import Chunk
from vector_search_lab.stores.base import SearchHit


class SqliteVecStore:
    """Persist chunk metadata in SQLite + vectors in a vec0 table."""

    def __init__(self, db_path: Path, *, dimensions: int) -> None:
        self.db_path = db_path
        self.dimensions = dimensions
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SqliteVecStore:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def init_schema(self, *, model_key: str, model_name: str, recreate_vec: bool = False) -> None:
        conn = self.connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                source_path TEXT NOT NULL,
                heading_path TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                char_start INTEGER NOT NULL,
                char_end INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_path);
            """
        )
        if recreate_vec:
            conn.execute("DROP TABLE IF EXISTS vec_chunks")

        vec_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_chunks'"
        ).fetchone()
        if not vec_exists:
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE vec_chunks USING vec0(
                    chunk_rowid INTEGER PRIMARY KEY,
                    embedding float[{self.dimensions}] distance_metric=cosine
                )
                """
            )

        conn.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
            ("model_key", model_key),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
            ("model_name", model_name),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
            ("dimensions", str(self.dimensions)),
        )
        conn.commit()

    def clear(self) -> None:
        conn = self.connect()
        conn.execute("DELETE FROM vec_chunks")
        conn.execute("DELETE FROM chunks")
        conn.commit()

    def insert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )
        conn = self.connect()
        with conn:
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                if len(embedding) != self.dimensions:
                    raise ValueError(
                        f"Expected {self.dimensions}-dim vector, got {len(embedding)}"
                    )
                cursor = conn.execute(
                    """
                    INSERT INTO chunks(chunk_id, source_path, heading_path, text, char_start, char_end)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.source_path,
                        chunk.heading_path,
                        chunk.text,
                        chunk.char_start,
                        chunk.char_end,
                    ),
                )
                chunk_rowid = int(cursor.lastrowid)
                conn.execute(
                    "INSERT INTO vec_chunks(chunk_rowid, embedding) VALUES (?, ?)",
                    (chunk_rowid, serialize_float32(embedding)),
                )

    def count(self) -> int:
        conn = self.connect()
        row = conn.execute("SELECT count(*) FROM chunks").fetchone()
        return int(row[0]) if row else 0

    def search(self, query_vector: list[float], *, top_k: int) -> list[SearchHit]:
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query vector has {len(query_vector)} dims, expected {self.dimensions}"
            )
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT
                c.chunk_id,
                c.source_path,
                c.heading_path,
                c.text,
                v.distance AS score
            FROM vec_chunks v
            JOIN chunks c ON c.rowid = v.chunk_rowid
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (serialize_float32(query_vector), top_k),
        ).fetchall()
        return [
            SearchHit(
                chunk_id=str(row["chunk_id"]),
                source_path=str(row["source_path"]),
                heading_path=str(row["heading_path"]),
                text=str(row["text"]),
                score=float(row["score"]),
            )
            for row in rows
        ]
