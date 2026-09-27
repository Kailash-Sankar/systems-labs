#!/usr/bin/env bash
# Thin wrapper around clickhouse-client inside the lab container.
# Every script and Makefile target goes through here so there is exactly
# one place that knows how to reach the server.
set -euo pipefail

CONTAINER="${CH_CONTAINER:-ch-storage-lab}"

# ch <sql> [extra client args...]   -- run one query
# ch_stdin <sql> [extra args...]    -- run one query with data piped on stdin
ch() {
    local sql="$1"; shift
    docker exec -i "$CONTAINER" clickhouse-client --query "$sql" "$@"
}

ch_file() {
    docker exec -i "$CONTAINER" clickhouse-client --multiquery "$@"
}

require_up() {
    if ! docker exec "$CONTAINER" clickhouse-client --query "SELECT 1" >/dev/null 2>&1; then
        echo "error: container '$CONTAINER' is not running or not ready." >&2
        echo "       run 'make up' first." >&2
        exit 1
    fi
}

rule() { printf '\n%s\n' "--- $* ---"; }
