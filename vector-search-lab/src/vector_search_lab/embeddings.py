"""Local embedding models via FastEmbed (ONNX, no API keys)."""

from __future__ import annotations

from typing import Iterator

from fastembed import TextEmbedding

from vector_search_lab.config import EMBEDDING_MODELS

# Model-specific query/document prefixes (retrieval-tuned models)
_QUERY_PREFIX: dict[str, str] = {
    "bge-small": "query: ",
    "nomic": "search_query: ",
}
_DOC_PREFIX: dict[str, str] = {
    "bge-small": "passage: ",
    "nomic": "search_document: ",
}


class LocalEmbedder:
    """Wrap FastEmbed TextEmbedding with model keys from config."""

    def __init__(self, model_key: str) -> None:
        if model_key not in EMBEDDING_MODELS:
            known = ", ".join(sorted(EMBEDDING_MODELS))
            raise ValueError(f"Unknown model {model_key!r}. Choose from: {known}")
        self.model_key = model_key
        self.model_name = EMBEDDING_MODELS[model_key]
        self._model = TextEmbedding(model_name=self.model_name)
        self._dimensions: int | None = None

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            sample = self._to_list(next(self._model.embed(["dimension probe"])))
            self._dimensions = len(sample)
        return self._dimensions

    def _prefix_documents(self, texts: list[str]) -> list[str]:
        prefix = _DOC_PREFIX.get(self.model_key, "")
        if not prefix:
            return texts
        return [f"{prefix}{t}" if not t.startswith(prefix) else t for t in texts]

    def _prefix_query(self, text: str) -> str:
        prefix = _QUERY_PREFIX.get(self.model_key, "")
        if not prefix or text.startswith(prefix):
            return text
        return f"{prefix}{text}"

    def _to_list(self, vec: object) -> list[float]:
        if hasattr(vec, "tolist"):
            return vec.tolist()  # type: ignore[no-any-return]
        return list(vec)  # type: ignore[arg-type]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prefixed = self._prefix_documents(texts)
        return [self._to_list(vec) for vec in self._model.embed(prefixed)]

    def embed_query(self, text: str) -> list[float]:
        prefixed = self._prefix_query(text)
        return self._to_list(next(self._model.embed([prefixed])))

    def embed_documents_iter(self, texts: list[str]) -> Iterator[list[float]]:
        prefixed = self._prefix_documents(texts)
        for vec in self._model.embed(prefixed):
            yield self._to_list(vec)
