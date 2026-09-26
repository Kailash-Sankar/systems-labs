"""RAG helpers: assemble context from SearchHit list and call OpenRouter."""

from __future__ import annotations

from vector_search_lab.openrouter import chat_completion
from vector_search_lab.search_runner import Backend, search_backend
from vector_search_lab.stores.base import SearchHit


def format_context(hits: list[SearchHit]) -> str:
    blocks: list[str] = []
    for i, hit in enumerate(hits, start=1):
        heading = f" · {hit.heading_path}" if hit.heading_path else ""
        blocks.append(
            f"[{i}] source: {hit.source_path}{heading}\n{hit.text.strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def build_rag_messages(query: str, hits: list[SearchHit]) -> list[dict[str, str]]:
    context = format_context(hits)
    system = (
        "You answer questions using ONLY the provided context. "
        "If the context is insufficient, say so. Cite sources using [n] notation "
        "matching the context blocks."
    )
    user = f"Context:\n{context}\n\nQuestion: {query}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def retrieve_and_answer(
    query: str,
    *,
    backend: Backend = Backend.sqlite,
    model_key: str = "bge-small",
    top_k: int = 5,
    llm_model: str | None = None,
) -> dict[str, object]:
    """Retrieve top-k chunks, optionally generate an LLM answer via OpenRouter."""
    retrieval = search_backend(
        backend,
        query,
        model_key=model_key,
        top_k=top_k,
    )
    if retrieval.error:
        return {
            "query": query,
            "backend": backend.value,
            "error": retrieval.error,
            "hits": [],
            "answer": None,
            "timing_ms": {"embed": retrieval.embed_ms, "search": retrieval.search_ms},
        }

    messages = build_rag_messages(query, retrieval.hits)
    answer = chat_completion(messages=messages, model=llm_model)

    return {
        "query": query,
        "backend": backend.value,
        "hits": retrieval.hits,
        "answer": answer,
        "timing_ms": {
            "embed": retrieval.embed_ms,
            "search": retrieval.search_ms,
            "total_retrieval": retrieval.total_ms,
        },
        "context": format_context(retrieval.hits),
    }
