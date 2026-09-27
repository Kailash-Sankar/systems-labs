#!/usr/bin/env bash
# Isolate node3 from node1+node2 on the Docker bridge (real network partition).
set -euo pipefail

cd "$(dirname "$0")/.."

ACTION="${1:-}"
NETWORK="cap-partition_capnet"
CONTAINER="$(docker compose ps -q node3 2>/dev/null || true)"

if [[ -z "$CONTAINER" ]]; then
  echo "node3 container not running — start with: make up NODES=3" >&2
  exit 1
fi

is_connected() {
  docker inspect "$CONTAINER" \
    --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' \
    | grep -qw "$NETWORK"
}

case "$ACTION" in
  on)
    if is_connected; then
      docker network disconnect "$NETWORK" "$CONTAINER"
    fi
    echo "[partition] ON — node3 disconnected from $NETWORK"
    ;;
  off)
    if ! is_connected; then
      docker network connect "$NETWORK" "$CONTAINER"
    fi
    echo "[partition] OFF — node3 connected to $NETWORK"
    ;;
  status)
    if is_connected; then
      echo "connected"
    else
      echo "isolated"
    fi
    ;;
  *)
    echo "Usage: $0 on|off|status" >&2
    exit 1
    ;;
esac
