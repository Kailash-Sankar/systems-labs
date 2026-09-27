"""Phase 5 — Last-Write-Wins merge on heal (explicit, wrong for counters on purpose)."""

import httpx

from cap_partition.config import Settings
from cap_partition.replication.sync_quorum import other_peers
from cap_partition.store import ScoreRecord, ScoreStore


def pick_lww_winner(records: list[ScoreRecord]) -> ScoreRecord:
    """Winner by (updated_at, version, value) — newest timestamp wins ties by version."""
    if not records:
        raise ValueError("need at least one record to merge")
    return max(records, key=lambda record: (record.updated_at, record.version, record.value))


async def fetch_peer_record(client: httpx.AsyncClient, url: str) -> ScoreRecord:
    response = await client.get(f"{url}/internal/score")
    response.raise_for_status()
    body = response.json()
    return ScoreRecord(
        value=int(body["score"]),
        version=int(body["version"]),
        updated_at=float(body["updated_at"]),
    )


async def push_lww_peer(
    client: httpx.AsyncClient,
    url: str,
    record: ScoreRecord,
) -> bool:
    response = await client.post(
        f"{url}/internal/lww",
        json={
            "score": record.value,
            "version": record.version,
            "updated_at": record.updated_at,
        },
    )
    response.raise_for_status()
    return bool(response.json()["applied"])


async def run_lww_merge(
    settings: Settings,
    store: ScoreStore,
    client: httpx.AsyncClient,
) -> ScoreRecord:
    """Exchange scores with peers, pick LWW winner, apply locally and push to peers."""
    peer_urls = other_peers(settings)
    local = await store.read()
    records = [local]
    for url in peer_urls:
        try:
            records.append(await fetch_peer_record(client, url))
        except httpx.HTTPError:
            continue

    winner = pick_lww_winner(records)
    await store.apply_lww(winner)
    for url in peer_urls:
        try:
            await push_lww_peer(client, url, winner)
        except httpx.HTTPError:
            continue
    return winner


async def run_catchup_sync(
    settings: Settings,
    store: ScoreStore,
    client: httpx.AsyncClient,
) -> ScoreRecord:
    """Pull highest-version record from peers into local store (CP heal path)."""
    peer_urls = other_peers(settings)
    local = await store.read()
    records = [local]
    for url in peer_urls:
        try:
            records.append(await fetch_peer_record(client, url))
        except httpx.HTTPError:
            continue

    winner = max(records, key=lambda record: record.version)
    if winner.version > local.version:
        await store.apply_push(winner, winner.version - 1)
    return await store.read()
