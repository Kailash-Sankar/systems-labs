import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class RunMetrics:
    reads_total: int = 0
    writes_total: int = 0
    errors_total: int = 0
    min_score_seen: int | None = None
    max_score_seen: int | None = None
    write_latencies_ms: list[float] = field(default_factory=list)
    read_latencies_ms: list[float] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def record_read(self, score: int, latency_ms: float) -> None:
        self.reads_total += 1
        self.read_latencies_ms.append(latency_ms)
        self._observe_score(score)

    def record_write(self, score: int, latency_ms: float) -> None:
        self.writes_total += 1
        self.write_latencies_ms.append(latency_ms)
        self._observe_score(score)

    def record_error(self) -> None:
        self.errors_total += 1

    def _observe_score(self, score: int) -> None:
        if self.min_score_seen is None or score < self.min_score_seen:
            self.min_score_seen = score
        if self.max_score_seen is None or score > self.max_score_seen:
            self.max_score_seen = score

    @property
    def max_value_spread(self) -> int:
        if self.min_score_seen is None or self.max_score_seen is None:
            return 0
        return self.max_score_seen - self.min_score_seen

    def snapshot(self) -> dict[str, int | float | None]:
        return {
            "reads_total": self.reads_total,
            "writes_total": self.writes_total,
            "errors_total": self.errors_total,
            "min_score_seen": self.min_score_seen,
            "max_score_seen": self.max_score_seen,
            "max_value_spread": self.max_value_spread,
        }


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._metrics = RunMetrics()

    async def metrics(self) -> RunMetrics:
        async with self._lock:
            return self._metrics

    async def reset(self) -> None:
        async with self._lock:
            self._metrics = RunMetrics()
