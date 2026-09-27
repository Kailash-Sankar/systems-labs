from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from cap_partition.config import Settings, get_settings
from cap_partition.metrics import MetricsRegistry
from cap_partition.replication import build_replication
from cap_partition.replication.base import QuorumNotMetError
from cap_partition.store import ScoreRecord, ScoreStore


def record_to_response(record: ScoreRecord, node_id: str) -> dict[str, int | str | float]:
    return {
        "score": record.value,
        "version": record.version,
        "updated_at": record.updated_at,
        "node": node_id,
    }


class PushRequest(BaseModel):
    score: int = Field(ge=0)
    version: int = Field(ge=0)
    updated_at: float
    expected_version: int = Field(ge=0)


class LwwPushRequest(BaseModel):
    score: int = Field(ge=0)
    version: int = Field(ge=0)
    updated_at: float


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    store = ScoreStore()
    http_client = httpx.AsyncClient(timeout=10.0)
    strategy = build_replication(settings, store, http_client=http_client)

    app.state.settings = settings
    app.state.store = store
    app.state.strategy = strategy
    app.state.metrics = MetricsRegistry()
    app.state.http_client = http_client

    yield

    await http_client.aclose()


app = FastAPI(title="cap-partition", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    settings: Settings = app.state.settings
    return {
        "status": "ok",
        "node": settings.node_id,
        "replication": settings.replication,
    }


@app.get("/internal/score")
async def internal_score() -> dict[str, int | float]:
    store: ScoreStore = app.state.store
    record = await store.read()
    return {
        "score": record.value,
        "version": record.version,
        "updated_at": record.updated_at,
    }


@app.post("/internal/push")
async def internal_push(body: PushRequest) -> dict[str, bool]:
    store: ScoreStore = app.state.store
    record = ScoreRecord(
        value=body.score,
        version=body.version,
        updated_at=body.updated_at,
    )
    applied = await store.apply_push(record, body.expected_version)
    return {"applied": applied}


@app.post("/internal/lww")
async def internal_lww(body: LwwPushRequest) -> dict[str, bool]:
    store: ScoreStore = app.state.store
    record = ScoreRecord(
        value=body.score,
        version=body.version,
        updated_at=body.updated_at,
    )
    applied = await store.apply_lww(record)
    return {"applied": applied}


@app.post("/admin/merge")
async def admin_merge() -> dict[str, int | str | float]:
    """Run LWW merge against all reachable peers (Phase 5 anti-entropy)."""
    from cap_partition.replication.merge import run_lww_merge

    settings: Settings = app.state.settings
    store: ScoreStore = app.state.store
    client: httpx.AsyncClient = app.state.http_client
    winner = await run_lww_merge(settings, store, client)
    return record_to_response(winner, settings.node_id)


@app.post("/admin/sync")
async def admin_sync() -> dict[str, int | str | float]:
    """Pull highest version from peers (CP heal catch-up)."""
    from cap_partition.replication.merge import run_catchup_sync

    settings: Settings = app.state.settings
    store: ScoreStore = app.state.store
    client: httpx.AsyncClient = app.state.http_client
    record = await run_catchup_sync(settings, store, client)
    return record_to_response(record, settings.node_id)


@app.get("/score")
async def get_score() -> dict[str, int | str | float]:
    settings: Settings = app.state.settings
    try:
        record = await app.state.strategy.read_score()
    except QuorumNotMetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return record_to_response(record, settings.node_id)


@app.post("/score/increment")
async def increment_score() -> dict[str, int | str | float]:
    settings: Settings = app.state.settings
    try:
        record = await app.state.strategy.increment_score()
    except QuorumNotMetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return record_to_response(record, settings.node_id)


@app.post("/admin/reset")
async def admin_reset() -> dict[str, str]:
    await app.state.store.reset()
    await app.state.metrics.reset()
    return {"status": "reset"}


@app.get("/admin/metrics")
async def admin_metrics() -> dict[str, int | float | None]:
    metrics = await app.state.metrics.metrics()
    return metrics.snapshot()
