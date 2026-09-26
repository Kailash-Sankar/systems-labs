"""FastAPI UI — compare search across backends + optional RAG."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vector_search_lab.config import DEFAULT_MODEL, EMBEDDING_MODELS
from vector_search_lab.env_settings import openrouter_api_key, openrouter_model
from vector_search_lab.rag import build_rag_messages, format_context, retrieve_and_answer
from vector_search_lab.search_runner import ALL_BACKENDS, Backend, search_all_backends
from vector_search_lab.openrouter import OpenRouterError, chat_completion

_STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Vector Search Lab", version="0.1.0")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


class CompareRequest(BaseModel):
    query: str = Field(min_length=1)
    model: str = DEFAULT_MODEL
    top_k: int = Field(default=5, ge=1, le=20)


class RagRequest(BaseModel):
    query: str = Field(min_length=1)
    backend: Backend = Backend.sqlite
    model: str = DEFAULT_MODEL
    top_k: int = Field(default=5, ge=1, le=20)
    llm_model: str | None = None


def _hit_to_dict(hit: object) -> dict[str, object]:
    return {
        "chunk_id": hit.chunk_id,
        "source_path": hit.source_path,
        "heading_path": hit.heading_path,
        "text": hit.text,
        "score": hit.score,
    }


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "embedding_models": list(EMBEDDING_MODELS.keys()),
        "backends": [b.value for b in ALL_BACKENDS],
        "openrouter_configured": openrouter_api_key() is not None,
        "openrouter_model": openrouter_model(),
    }


@app.post("/api/compare")
def compare_search(body: CompareRequest) -> dict[str, object]:
    if body.model not in EMBEDDING_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model {body.model!r}")

    results = search_all_backends(
        body.query,
        model_key=body.model,
        top_k=body.top_k,
    )

    payload_results = []
    for r in results:
        payload_results.append(
            {
                "backend": r.backend,
                "embed_ms": round(r.embed_ms, 2),
                "search_ms": round(r.search_ms, 2),
                "total_ms": round(r.total_ms, 2),
                "chunk_count": r.chunk_count,
                "error": r.error,
                "hits": [_hit_to_dict(h) for h in r.hits],
            }
        )

    ok_results = [r for r in results if not r.error]
    fastest = min(ok_results, key=lambda r: r.total_ms).backend if ok_results else None

    return {
        "query": body.query,
        "model": body.model,
        "top_k": body.top_k,
        "fastest_backend": fastest,
        "results": payload_results,
    }


@app.post("/api/rag")
def rag_answer(body: RagRequest) -> dict[str, object]:
    if body.model not in EMBEDDING_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model {body.model!r}")

    try:
        out = retrieve_and_answer(
            body.query,
            backend=body.backend,
            model_key=body.model,
            top_k=body.top_k,
            llm_model=body.llm_model,
        )
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if out.get("error"):
        raise HTTPException(status_code=400, detail=str(out["error"]))

    hits = out["hits"]
    return {
        "query": body.query,
        "backend": body.backend.value,
        "model": body.model,
        "llm_model": body.llm_model or openrouter_model(),
        "timing_ms": out.get("timing_ms", {}),
        "hits": [_hit_to_dict(h) for h in hits],
        "context": out.get("context", ""),
        "answer": out.get("answer"),
    }


@app.post("/api/rag/preview")
def rag_preview_context(body: RagRequest) -> dict[str, object]:
    """Build the RAG prompt context without calling the LLM."""
    from vector_search_lab.search_runner import search_backend

    if body.model not in EMBEDDING_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model {body.model!r}")

    retrieval = search_backend(
        body.backend,
        body.query,
        model_key=body.model,
        top_k=body.top_k,
    )
    if retrieval.error:
        raise HTTPException(status_code=400, detail=retrieval.error)

    messages = build_rag_messages(body.query, retrieval.hits)
    return {
        "query": body.query,
        "backend": body.backend.value,
        "timing_ms": {
            "embed": round(retrieval.embed_ms, 2),
            "search": round(retrieval.search_ms, 2),
            "total": round(retrieval.total_ms, 2),
        },
        "hits": [_hit_to_dict(h) for h in retrieval.hits],
        "context": format_context(retrieval.hits),
        "messages": messages,
    }


def main() -> None:
    import uvicorn

    uvicorn.run(
        "vector_search_lab.web.app:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
