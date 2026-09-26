import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def default_corpus_path() -> Path:
    """Default markdown root: ./corpus in repo, or CORPUS_PATH env override."""
    override = os.getenv("CORPUS_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "corpus"


DEFAULT_CORPUS = default_corpus_path()

# Embedding models to compare (FastEmbed / ONNX, all local)
EMBEDDING_MODELS: dict[str, str] = {
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",       # 384 dims, fast baseline
    "bge-small": "BAAI/bge-small-en-v1.5",                    # 384 dims, strong retrieval
    "nomic": "nomic-ai/nomic-embed-text-v1.5",                # 768 dims, longer context
}

DEFAULT_MODEL = "bge-small"
DEFAULT_TOP_K = 5

# Where sqlite-vec stores its DB (gitignored)
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SQLITE_DB_PATH = DATA_DIR / "corpus-vectors.db"  # legacy default; prefer sqlite_db_path()


def sqlite_db_path(model_key: str = DEFAULT_MODEL) -> Path:
    """Per-model DB path — dimensions differ across models (384 vs 768)."""
    return DATA_DIR / f"corpus-{model_key}.db"


# Qdrant (Phase 3+) — docker compose service on :6333
QDRANT_URL = "http://localhost:6333"


def qdrant_collection_name(model_key: str = DEFAULT_MODEL) -> str:
    """One collection per embedding model (vector size must match)."""
    safe = model_key.replace("-", "_")
    return f"corpus_{safe}"


# Redis Stack (Phase 4+) — docker compose service on :6379
REDIS_URL = "redis://localhost:6380"


def redis_index_name(model_key: str = DEFAULT_MODEL) -> str:
    """RediSearch index name — one per embedding model."""
    safe = model_key.replace("-", "_")
    return f"idx:corpus_{safe}"


def redis_key_prefix(model_key: str = DEFAULT_MODEL) -> str:
    """HASH key prefix for chunk documents in Redis."""
    safe = model_key.replace("-", "_")
    return f"chunk:corpus_{safe}:"


# Milvus (Phase 5+) — docker compose standalone on :19530
MILVUS_URI = "http://localhost:19530"


def milvus_collection_name(model_key: str = DEFAULT_MODEL) -> str:
    """One collection per embedding model (vector size must match)."""
    safe = model_key.replace("-", "_")
    return f"corpus_{safe}"


# Chunking — markdown notes are prose-heavy; start conservative
CHUNK_SIZE = 800       # characters (~150–200 tokens)
CHUNK_OVERLAP = 120    # overlap so headings don't orphan context
