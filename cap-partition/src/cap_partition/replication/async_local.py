import asyncio
import logging

import httpx

from cap_partition.config import Settings
from cap_partition.replication.sync_quorum import SyncQuorumReplication
from cap_partition.store import ScoreRecord, ScoreStore

logger = logging.getLogger(__name__)


class AsyncLocalReplication(SyncQuorumReplication):
    """Phase 2b / 4 — local ACK write, best-effort background replicate; local read."""

    async def read_score(self) -> ScoreRecord:
        return await self._store.read()

    async def increment_score(self) -> ScoreRecord:
        record = await self._store.increment()
        expected_version = record.version - 1
        asyncio.create_task(self._replicate_best_effort(record, expected_version))
        return record

    async def _replicate_best_effort(
        self,
        record: ScoreRecord,
        expected_version: int,
    ) -> None:
        for url in self._peer_urls:
            try:
                await self._push_peer(url, record, expected_version)
            except httpx.HTTPError as exc:
                logger.debug("background push to %s failed: %s", url, exc)
