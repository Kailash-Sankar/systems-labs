from cap_partition.store import ScoreRecord


class QuorumNotMetError(Exception):
    """Raised when fewer than W write or R read ACKs are reachable."""


def record_key(record: ScoreRecord) -> tuple[int, int]:
    return record.value, record.version
