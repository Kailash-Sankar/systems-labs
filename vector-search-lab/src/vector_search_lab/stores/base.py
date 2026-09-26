"""Shared types for vector store backends."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchHit:
    """One retrieved chunk from a vector search."""

    chunk_id: str
    source_path: str
    heading_path: str
    text: str
    score: float  # distance — lower is more similar (cosine distance in sqlite-vec)
