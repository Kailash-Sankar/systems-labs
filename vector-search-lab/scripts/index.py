#!/usr/bin/env python3
"""Index a markdown corpus into a vector store."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from vector_search_lab.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DEFAULT_MODEL,
    DEFAULT_CORPUS,
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
from vector_search_lab.documents import load_corpus
from vector_search_lab.embeddings import LocalEmbedder
from vector_search_lab.stores.milvus_store import MilvusStore
from vector_search_lab.stores.qdrant_store import QdrantStore
from vector_search_lab.stores.redis_store import RedisStore
from vector_search_lab.stores.sqlite_vec import SqliteVecStore

app = typer.Typer(help="Index markdown into sqlite-vec, Qdrant, Redis, or Milvus")
console = Console()


class Backend(str, Enum):
    sqlite = "sqlite"
    qdrant = "qdrant"
    redis = "redis"
    milvus = "milvus"


@app.command()
def main(
    corpus: Path = typer.Option(
        DEFAULT_CORPUS,
        "--corpus",
        "-c",
        help="Root directory of markdown files",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
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
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        help="Drop and recreate the index for this model",
    ),
    batch_size: int = typer.Option(
        32,
        "--batch-size",
        help="Embedding batch size",
        min=1,
    ),
) -> None:
    """Chunk corpus, embed locally, and store vectors."""
    if model not in EMBEDDING_MODELS:
        console.print(f"[red]Unknown model {model!r}.[/red] Choose: {', '.join(EMBEDDING_MODELS)}")
        raise typer.Exit(code=1)

    console.print(f"[bold]Corpus:[/bold]  {corpus}")
    console.print(f"[bold]Model:[/bold]   {model} ({EMBEDDING_MODELS[model]})")
    console.print(f"[bold]Backend:[/bold] {backend.value}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Loading and chunking markdown…", total=None)
        chunks = load_corpus(
            corpus,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        progress.update(task, description=f"Loaded {len(chunks)} chunks")

        embedder = LocalEmbedder(model)

        progress.update(task, description=f"Embedding {len(chunks)} chunks…")
        texts = [c.text for c in chunks]
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            embeddings.extend(embedder.embed_documents(batch))

        if backend == Backend.sqlite:
            db_path = sqlite_db_path(model)
            store = SqliteVecStore(db_path, dimensions=embedder.dimensions)
            if rebuild and db_path.exists():
                db_path.unlink()
            store.connect()
            store.init_schema(
                model_key=model,
                model_name=EMBEDDING_MODELS[model],
                recreate_vec=rebuild,
            )
            store.clear()
            progress.update(task, description="Writing to sqlite-vec…")
            store.insert_chunks(chunks, embeddings)
            store.close()
            target = str(db_path)
        elif backend == Backend.qdrant:
            collection = qdrant_collection_name(model)
            store = QdrantStore(
                url=QDRANT_URL,
                collection_name=collection,
                dimensions=embedder.dimensions,
            )
            store.connect()
            if rebuild:
                store.clear()
            else:
                store.init_schema(
                    model_key=model,
                    model_name=EMBEDDING_MODELS[model],
                    recreate=False,
                )
                if store.count() > 0:
                    store.clear()
            progress.update(task, description=f"Writing to Qdrant ({collection})…")
            store.insert_chunks(chunks, embeddings)
            store.close()
            target = f"{QDRANT_URL} → {collection}"
        elif backend == Backend.redis:
            index_name = redis_index_name(model)
            key_prefix = redis_key_prefix(model)
            store = RedisStore(
                url=REDIS_URL,
                index_name=index_name,
                key_prefix=key_prefix,
                dimensions=embedder.dimensions,
            )
            store.connect()
            if rebuild:
                store.clear()
            else:
                store.init_schema(
                    model_key=model,
                    model_name=EMBEDDING_MODELS[model],
                    recreate=False,
                )
                if store.count() > 0:
                    store.clear()
            progress.update(task, description=f"Writing to Redis ({index_name})…")
            store.insert_chunks(chunks, embeddings)
            store.close()
            target = f"{REDIS_URL} → {index_name}"
        else:
            collection = milvus_collection_name(model)
            store = MilvusStore(
                uri=MILVUS_URI,
                collection_name=collection,
                dimensions=embedder.dimensions,
            )
            store.connect()
            if rebuild:
                store.clear()
            else:
                store.init_schema(
                    model_key=model,
                    model_name=EMBEDDING_MODELS[model],
                    recreate=False,
                )
                if store.count() > 0:
                    store.clear()
            progress.update(task, description=f"Writing to Milvus ({collection})…")
            store.insert_chunks(chunks, embeddings)
            store.close()
            target = f"{MILVUS_URI} → {collection}"

    console.print(
        f"[green]Indexed {len(chunks)} chunks → {target} "
        f"({embedder.dimensions} dims, cosine)[/green]"
    )


if __name__ == "__main__":
    app()
