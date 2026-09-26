"""OpenRouter chat completions (OpenAI-compatible API)."""

from __future__ import annotations

import httpx

from vector_search_lab.env_settings import (
    openrouter_api_key,
    openrouter_base_url,
    openrouter_model,
)


class OpenRouterError(RuntimeError):
    pass


def chat_completion(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    timeout_s: float = 120.0,
) -> str:
    api_key = openrouter_api_key()
    if not api_key:
        raise OpenRouterError(
            "OPENROUTER_API_KEY is not set. Copy .env.sample to .env and add your key."
        )

    payload = {
        "model": model or openrouter_model(),
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/local/vector-search-lab",
        "X-Title": "vector-search-lab",
    }

    url = f"{openrouter_base_url()}/chat/completions"
    with httpx.Client(timeout=timeout_s) as client:
        response = client.post(url, json=payload, headers=headers)

    if response.status_code >= 400:
        raise OpenRouterError(f"OpenRouter HTTP {response.status_code}: {response.text[:500]}")

    data = response.json()
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"Unexpected OpenRouter response shape: {data!r}") from exc
