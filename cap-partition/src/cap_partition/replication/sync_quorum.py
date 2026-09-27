import asyncio
import time

import httpx

from cap_partition.config import Settings
from cap_partition.replication.base import QuorumNotMetError
from cap_partition.store import ScoreRecord, ScoreStore

MAX_INCREMENT_RETRIES = 40


def other_peers(settings: Settings) -> tuple[str, ...]:
    return tuple(url for url in settings.peers if settings.node_id not in url)


class SyncQuorumReplication:
    """Phase 2+ — W/R quorum over HTTP with CAS apply and optional RPC delay."""

    def __init__(
        self,
        settings: Settings,
        store: ScoreStore,
        client: httpx.AsyncClient,
    ) -> None:
        self._settings = settings
        self._store = store
        self._client = client
        self._peer_urls = other_peers(settings)

    async def _rpc_delay(self) -> None:
        if self._settings.rpc_delay_ms > 0:
            await asyncio.sleep(self._settings.rpc_delay_ms / 1000)

    async def _fetch_local_peer(self, url: str) -> ScoreRecord:
        await self._rpc_delay()
        response = await self._client.get(f"{url}/internal/score")
        response.raise_for_status()
        body = response.json()
        return ScoreRecord(
            value=int(body["score"]),
            version=int(body["version"]),
            updated_at=float(body["updated_at"]),
        )

    async def _push_peer(
        self,
        url: str,
        record: ScoreRecord,
        expected_version: int,
    ) -> bool:
        await self._rpc_delay()
        response = await self._client.post(
            f"{url}/internal/push",
            json={
                "score": record.value,
                "version": record.version,
                "updated_at": record.updated_at,
                "expected_version": expected_version,
            },
        )
        response.raise_for_status()
        return bool(response.json()["applied"])

    async def _fetch_all_records(self) -> list[ScoreRecord]:
        local = await self._store.read()
        results = await asyncio.gather(
            *(self._fetch_local_peer(url) for url in self._peer_urls),
            return_exceptions=True,
        )
        records = [local]
        for result in results:
            if isinstance(result, ScoreRecord):
                records.append(result)
        return records

    def _pick_read_quorum(self, records: list[ScoreRecord]) -> ScoreRecord:
        if len(records) < self._settings.r:
            raise QuorumNotMetError(
                f"read quorum not met: need R={self._settings.r}, reachable={len(records)}"
            )
        # W + R > N: highest version among R+ responses overlaps latest write quorum.
        return max(records, key=lambda record: record.version)

    async def read_score(self) -> ScoreRecord:
        records = await self._fetch_all_records()
        if len(records) < self._settings.r:
            raise QuorumNotMetError(
                f"read quorum not met: need R={self._settings.r}, reachable={len(records)}"
            )
        return self._pick_read_quorum(records)

    async def increment_score(self) -> ScoreRecord:
        records = await self._fetch_all_records()
        if len(records) < self._settings.w:
            raise QuorumNotMetError(
                f"write quorum not met: need W={self._settings.w}, reachable={len(records)}"
            )

        current = max(records, key=lambda record: record.version)
        new = ScoreRecord(
            value=current.value + 1,
            version=current.version + 1,
            updated_at=time.time(),
        )

        for attempt in range(MAX_INCREMENT_RETRIES):
            results = await asyncio.gather(
                self._store.apply_push(new, current.version),
                *(
                    self._push_peer(url, new, current.version)
                    for url in self._peer_urls
                ),
                return_exceptions=True,
            )
            acks = sum(1 for result in results if result is True)
            if acks >= self._settings.w:
                return new

            await asyncio.sleep(0.01 * (attempt + 1))

        raise QuorumNotMetError(
            f"write quorum not met after {MAX_INCREMENT_RETRIES} retries"
        )
