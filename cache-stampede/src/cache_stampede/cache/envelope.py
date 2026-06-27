import json
import time
from dataclasses import dataclass

from cache_stampede.cache.base import CachedItem


@dataclass(frozen=True)
class CacheEnvelope:
    """Cached item plus timestamp for soft/hard SWR semantics."""

    item: CachedItem
    cached_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.item.id,
                "name": self.item.name,
                "payload": self.item.payload,
                "cached_at": self.cached_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "CacheEnvelope":
        data = json.loads(raw)
        item = CachedItem(id=data["id"], name=data["name"], payload=data["payload"])
        return cls(item=item, cached_at=float(data["cached_at"]))

    def age_sec(self) -> float:
        return time.time() - self.cached_at
