#!/usr/bin/env python3
"""Semantic search over indexed markdown chunks."""

from __future__ import annotations

from enum import Enum

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vector_search_lab.config import (
    DEFAULT_MODEL,
    DEFAULT_TOP_K,
    EMBEDDING_MODELS,
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
from vector_search_lab.stores.milvus_store import MilvusStore
from vector_search_lab.stores.qdrant_store import QdrantStore
from vector_search_lab.stores.redis_store import RedisStore
from vector_search_lab.stores.sqlite_vec import SqliteVecStore

app = typer.Typer(help="Search indexed corpus (sqlite-vec, Qdrant, Redis, Milvus)")
console = Console()


class Backend(str, Enum):
    sqlite = "sqlite"
    qdrant = "qdrant"
    redis = "redis"
    milvus = "milvus"


def _truncate(text: str, limit: int = 280) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


@app.command()
def main(
    query: str = typer.Argument(..., help="Natural-language search query"),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help=f"Embedding model key ({', '.join(EMBEDDING_MODELS)})",
    ),
    backend: Backend = typer.Option(
        Backend.sqlite,
        "--backend",
        "-b",
        help="Vector store backend",
    ),
    top_k: int = typer.Option(
        DEFAULT_TOP_K,
        "--top-k",
        "-k",
        help="Number of results",
        min=1,
    ),
    filter_source: str | None = typer.Option(
        None,
        "--filter-source",
        help="Qdrant/Redis/Milvus: restrict to exact source_path match",
    ),
) -> None:
    """Embed query and retrieve nearest chunks by cosine distance."""
    if model not in EMBEDDING_MODELS:
        console.print(f"[red]Unknown model {model!r}.[/red] Choose: {', '.join(EMBEDDING_MODELS)}")
        raise typer.Exit(code=1)

    embedder = LocalEmbedder(model)

    if backend == Backend.sqlite:
        if filter_source:
            console.print("[yellow]--filter-source ignored for sqlite.[/yellow]")
        db_path = sqlite_db_path(model)
        if not db_path.exists():
            console.print(
                f"[red]No index at {db_path}.[/red] Run: "
                f"uv run python scripts/index.py --model {model}"
            )
            raise typer.Exit(code=1)
        store = SqliteVecStore(db_path, dimensions=embedder.dimensions)
        store.connect()
        chunk_count = store.count()
        backend_label = f"sqlite-vec · {db_path.name}"
    elif backend == Backend.qdrant:
        collection = qdrant_collection_name(model)
        store = QdrantStore(
            url=QDRANT_URL,
            collection_name=collection,
            dimensions=embedder.dimensions,
        )
        store.connect()
        chunk_count = store.count()
        if chunk_count == 0:
            console.print(
                f"[red]Qdrant collection {collection!r} is empty.[/red] Run: "
                f"uv run python scripts/index.py --backend qdrant --model {model}"
            )
            raise typer.Exit(code=1)
        backend_label = f"Qdrant · {collection}"
    elif backend == Backend.redis:
        index_name = redis_index_name(model)
        store = RedisStore(
            url=REDIS_URL,
            index_name=index_name,
            key_prefix=redis_key_prefix(model),
            dimensions=embedder.dimensions,
        )
        store.connect()
        chunk_count = store.count()
        if chunk_count == 0:
            console.print(
                f"[red]Redis index {index_name!r} is empty.[/red] Run: "
                f"uv run python scripts/index.py --backend redis --model {model}"
            )
            raise typer.Exit(code=1)
        backend_label = f"Redis · {index_name}"
    elif backend == Backend.milvus:
        collection = milvus_collection_name(model)
        store = MilvusStore(
            uri=MILVUS_URI,
            collection_name=collection,
            dimensions=embedder.dimensions,
        )
        store.connect()
        chunk_count = store.count()
        if chunk_count == 0:
            console.print(
                f"[red]Milvus collection {collection!r} is empty.[/red] Run: "
                f"uv run python scripts/index.py --backend milvus --model {model}"
            )
            raise typer.Exit(code=1)
        backend_label = f"Milvus · {collection}"

    if chunk_count == 0:
        console.print("[yellow]Index exists but has 0 chunks. Re-run index.py[/yellow]")
        raise typer.Exit(code=1)

    query_vector = embedder.embed_query(query)
    if filter_source and backend in (Backend.qdrant, Backend.redis, Backend.milvus):
        hits = store.search(query_vector, top_k=top_k, source_path=filter_source)
    else:
        hits = store.search(query_vector, top_k=top_k)
    store.close()

    console.print(f"[bold]Query:[/bold] {query}")
    console.print(
        f"[dim]Model: {model} · {backend_label} · {chunk_count} chunks · top {top_k}[/dim]\n"
    )

    if not hits:
        console.print("[yellow]No results.[/yellow]")
        raise typer.Exit(code=0)

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Source", width=36)
    table.add_column("Heading", width=28)
    table.add_column("Snippet")

    for i, hit in enumerate(hits, start=1):
        heading = hit.heading_path or "—"
        table.add_row(
            str(i),
            f"{hit.score:.4f}",
            hit.source_path,
            _truncate(heading, 26),
            _truncate(hit.text, 120),
        )

    console.print(table)

    best = hits[0]
    console.print(
        Panel(
            best.text,
            title=f"Top hit · {best.source_path}"
            + (f" · {best.heading_path}" if best.heading_path else ""),
            subtitle=f"cosine distance {best.score:.4f}",
        )
    )


if __name__ == "__main__":
    app()
