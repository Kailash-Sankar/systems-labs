"""Load environment variables from .env at project root."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _PROJECT_ROOT / ".env"

load_dotenv(_ENV_PATH)


def openrouter_api_key() -> str | None:
    value = os.getenv("OPENROUTER_API_KEY", "").strip()
    return value or None


def openrouter_model() -> str:
    return os.getenv("OPENROUTER_MODEL", "cohere/north-mini-code:free").strip()


def openrouter_base_url() -> str:
    return os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
