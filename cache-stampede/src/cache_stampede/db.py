import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ItemRecord:
    id: int
    name: str
    payload: str


class OriginDB:
    """SQLite origin with intentional slow reads."""

    def __init__(self, db_path: str, sleep_ms: int) -> None:
        self._db_path = db_path
        self._sleep_ms = sleep_ms

    def get_item(self, item_id: int) -> ItemRecord:
        time.sleep(self._sleep_ms / 1000.0)

        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT id, name, payload FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            raise KeyError(f"item {item_id} not found")

        return ItemRecord(id=row[0], name=row[1], payload=row[2])


def ensure_db_exists(db_path: str) -> None:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(
            f"SQLite database not found at {db_path}. Run: make seed"
        )
