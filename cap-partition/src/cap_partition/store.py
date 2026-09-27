import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreRecord:
    value: int
    version: int
    updated_at: float


class ScoreStore:
    """In-memory counter with monotonic version for future merge/LWW phases."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._value = 0
        self._version = 0
        self._updated_at = time.time()

    async def read(self) -> ScoreRecord:
        async with self._lock:
            return ScoreRecord(
                value=self._value,
                version=self._version,
                updated_at=self._updated_at,
            )

    async def increment(self) -> ScoreRecord:
        async with self._lock:
            self._value += 1
            self._version += 1
            self._updated_at = time.time()
            return ScoreRecord(
                value=self._value,
                version=self._version,
                updated_at=self._updated_at,
            )

    async def apply_push(self, record: ScoreRecord, expected_version: int) -> bool:
        """Apply a replicated write; allow catch-up when this node is behind the quorum."""
        async with self._lock:
            if self._version == record.version and self._value == record.value:
                return True
            if record.version < self._version:
                return False
            if self._version < expected_version:
                self._value = record.value
                self._version = record.version
                self._updated_at = record.updated_at
                return True
            if (
                self._version == expected_version
                and record.version == expected_version + 1
            ):
                self._value = record.value
                self._version = record.version
                self._updated_at = record.updated_at
                return True
            return False

    async def apply_lww(self, record: ScoreRecord) -> bool:
        """Last-write-wins merge — teaching only; loses counter increments on conflict."""
        async with self._lock:
            current = (self._updated_at, self._version, self._value)
            incoming = (record.updated_at, record.version, record.value)
            if incoming <= current:
                return False
            self._value = record.value
            self._version = record.version
            self._updated_at = record.updated_at
            return True

    async def reset(self) -> None:
        async with self._lock:
            self._value = 0
            self._version = 0
            self._updated_at = time.time()
