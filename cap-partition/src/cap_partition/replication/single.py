from cap_partition.store import ScoreRecord, ScoreStore


class SingleNodeReplication:
    """Phase 1 — local in-memory store only, no peer RPC."""

    def __init__(self, store: ScoreStore) -> None:
        self._store = store

    async def read_score(self) -> ScoreRecord:
        return await self._store.read()

    async def increment_score(self) -> ScoreRecord:
        return await self._store.increment()
