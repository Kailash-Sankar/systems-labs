#!/usr/bin/env python3
"""RAG: retrieve indexed chunks and answer via OpenRouter."""

from __future__ import annotations

from enum import Enum

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from vector_search_lab.config import DEFAULT_MODEL, EMBEDDING_MODELS
from vector_search_lab.env_settings import openrouter_model
from vector_search_lab.rag import format_context, retrieve_and_answer
from vector_search_lab.search_runner import Backend

app = typer.Typer(help="Retrieve corpus chunks and answer with OpenRouter")
console = Console()


def _truncate(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


@app.command()
def main(
    query: str = typer.Argument(..., help="Question to answer from indexed corpus"),
    backend: Backend = typer.Option(
        Backend.sqlite,
        "--backend",
        "-b",
        help="Vector store for retrieval",
    ),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help=f"Embedding model ({', '.join(EMBEDDING_MODELS)})",
    ),
    top_k: int = typer.Option(5, "--top-k", "-k", min=1),
    context_only: bool = typer.Option(
        False,
        "--context-only",
        help="Print retrieved context only; skip OpenRouter LLM call",
    ),
    llm_model: str | None = typer.Option(
        None,
        "--llm-model",
        help="OpenRouter model id (default: OPENROUTER_MODEL from .env)",
    ),
) -> None:
    if model not in EMBEDDING_MODELS:
        console.print(f"[red]Unknown embedding model {model!r}[/red]")
        raise typer.Exit(code=1)

    if context_only:
        from vector_search_lab.search_runner import search_backend

        result = search_backend(backend, query, model_key=model, top_k=top_k)
        if result.error:
            console.print(f"[red]{result.error}[/red]")
            raise typer.Exit(code=1)
        console.print(Panel(format_context(result.hits), title=f"Context · {backend.value}"))
        console.print(
            f"[dim]embed {result.embed_ms:.0f} ms · search {result.search_ms:.0f} ms[/dim]"
        )
        raise typer.Exit(code=0)

    console.print(f"[bold]Query:[/bold] {query}")
    console.print(
        f"[dim]Retrieve: {backend.value} · embed: {model} · LLM: {llm_model or openrouter_model()}[/dim]\n"
    )

    with console.status("Retrieving and generating…"):
        out = retrieve_and_answer(
            query,
            backend=backend,
            model_key=model,
            top_k=top_k,
            llm_model=llm_model,
        )

    if out.get("error"):
        console.print(f"[red]{out['error']}[/red]")
        raise typer.Exit(code=1)

    timing = out.get("timing_ms", {})
    console.print(
        f"[dim]Retrieval: embed {timing.get('embed', 0):.0f} ms · "
        f"search {timing.get('search', 0):.0f} ms[/dim]\n"
    )

    hits = out["hits"]
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=3)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Source", width=40)
    table.add_column("Snippet")
    for i, hit in enumerate(hits, start=1):
        table.add_row(
            str(i),
            f"{hit.score:.4f}",
            hit.source_path,
            _truncate(hit.text, 100),
        )
    console.print(table)
    console.print()

    answer = out.get("answer") or ""
    console.print(Panel(Markdown(answer), title="Answer", border_style="green"))


if __name__ == "__main__":
    app()
