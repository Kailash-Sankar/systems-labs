import httpx

from cap_partition.config import Settings
from cap_partition.replication.async_local import AsyncLocalReplication
from cap_partition.replication.single import SingleNodeReplication
from cap_partition.replication.sync_quorum import SyncQuorumReplication
from cap_partition.store import ScoreStore

ReplicationStrategy = SingleNodeReplication | SyncQuorumReplication | AsyncLocalReplication


def build_replication(
    settings: Settings,
    store: ScoreStore,
    http_client: httpx.AsyncClient | None = None,
) -> ReplicationStrategy:
    if settings.replication == "single":
        return SingleNodeReplication(store)
    if http_client is None:
        raise ValueError(f"{settings.replication!r} replication requires an httpx.AsyncClient")
    if settings.replication == "sync":
        return SyncQuorumReplication(settings, store, http_client)
    if settings.replication in ("async", "ap"):
        return AsyncLocalReplication(settings, store, http_client)
    raise ValueError(
        f"Replication mode {settings.replication!r} is not implemented yet "
        "(available: single, sync, async, ap)"
    )
