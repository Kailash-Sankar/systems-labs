from dataclasses import dataclass
from typing import Literal

CacheStatus = Literal["hit", "miss", "wait_hit", "stale", "early_refresh"]


def cache_key(item_id: int) -> str:
    return f"item:{item_id}"


@dataclass(frozen=True)
class CachedItem:
    id: int
    name: str
    payload: str

    def to_json(self) -> str:
        import json

        return json.dumps(
            {"id": self.id, "name": self.name, "payload": self.payload}
        )

    @classmethod
    def from_json(cls, raw: str) -> "CachedItem":
        import json

        data = json.loads(raw)
        return cls(id=data["id"], name=data["name"], payload=data["payload"])
