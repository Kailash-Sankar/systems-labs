#!/usr/bin/env python3
"""Compare retrieval quality across local embedding models."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from vector_search_lab.config import DEFAULT_TOP_K, EMBEDDING_MODELS, sqlite_db_path
from vector_search_lab.embeddings import LocalEmbedder
from vector_search_lab.stores.sqlite_vec import SqliteVecStore

app = typer.Typer(help="Compare embedding models on the same query")
console = Console()


def _truncate(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


@app.command()
def main(
    query: str = typer.Argument(..., help="Natural-language search query"),
    top_k: int = typer.Option(
        DEFAULT_TOP_K,
        "--top-k",
        "-k",
        help="Results per model",
        min=1,
    ),
    models: list[str] = typer.Option(
        list(EMBEDDING_MODELS.keys()),
        "--model",
        "-m",
        help="Model keys to compare (repeatable)",
    ),
) -> None:
    """Run the same query against each model index and print a side-by-side table."""
    unknown = [m for m in models if m not in EMBEDDING_MODELS]
    if unknown:
        console.print(f"[red]Unknown models:[/red] {', '.join(unknown)}")
        raise typer.Exit(code=1)

    console.print(f"[bold]Query:[/bold] {query}\n")

    results_by_model: dict[str, list[tuple[str, float]]] = {}
    missing: list[str] = []

    for model_key in models:
        db_path = sqlite_db_path(model_key)
        if not db_path.exists():
            missing.append(model_key)
            continue

        embedder = LocalEmbedder(model_key)
        store = SqliteVecStore(db_path, dimensions=embedder.dimensions)
        store.connect()
        if store.count() == 0:
            missing.append(model_key)
            store.close()
            continue

        hits = store.search(embedder.embed_query(query), top_k=top_k)
        store.close()
        results_by_model[model_key] = [
            (f"{hit.source_path} · {_truncate(hit.text, 48)}", hit.score) for hit in hits
        ]

    if missing:
        console.print(
            "[yellow]Missing or empty indexes:[/yellow] "
            + ", ".join(missing)
            + "\nRun: uv run python scripts/index.py --model <key> for each.\n"
        )

    if not results_by_model:
        raise typer.Exit(code=1)

    table = Table(title="Embedding model comparison", show_header=True, header_style="bold")
    table.add_column("Rank", style="dim", width=4)

    for model_key in models:
        if model_key in results_by_model:
            dims = LocalEmbedder(model_key).dimensions
            table.add_column(f"{model_key}\n({dims}d)", overflow="fold")

    for rank in range(top_k):
        row: list[str] = [str(rank + 1)]
        for model_key in models:
            if model_key not in results_by_model:
                continue
            hits = results_by_model[model_key]
            if rank < len(hits):
                label, score = hits[rank]
                row.append(f"{score:.3f}\n{label}")
            else:
                row.append("—")
        if len(row) > 1:
            table.add_row(*row)

    console.print(table)

    console.print(
        "\n[dim]Score = cosine distance (lower is better). "
        "Build all indexes first: "
        "for m in minilm bge-small nomic; do "
        "uv run python scripts/index.py --model $m; done[/dim]"
    )


if __name__ == "__main__":
    app()
