import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    replication: str
    node_id: str
    n: int
    w: int
    r: int
    peers: tuple[str, ...]
    rpc_delay_ms: int


def get_settings() -> Settings:
    peers_raw = os.getenv("PEERS", "")
    peers = tuple(part.strip().rstrip("/") for part in peers_raw.split(",") if part.strip())
    return Settings(
        replication=os.getenv("REPLICATION", "single"),
        node_id=os.getenv("NODE_ID", "node1"),
        n=int(os.getenv("N", "3")),
        w=int(os.getenv("W", "2")),
        r=int(os.getenv("R", "2")),
        peers=peers,
        rpc_delay_ms=int(os.getenv("RPC_DELAY_MS", "50")),
    )
