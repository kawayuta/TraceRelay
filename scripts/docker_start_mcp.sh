#!/bin/sh

set -eu

WORKSPACE="${SCHEMALEDGER_WORKSPACE:-/app/workspace}"
DSN="${SCHEMALEDGER_POSTGRES_DSN:-postgresql://postgres:postgres@postgres:5432/schemaledger_fresh}"
HOST="${SCHEMALEDGER_MCP_HOST:-0.0.0.0}"
PORT="${SCHEMALEDGER_MCP_PORT:-5063}"
TRANSPORT="${SCHEMALEDGER_MCP_TRANSPORT:-sse}"

slg db apply-schema --workspace "$WORKSPACE" --dsn "$DSN" --reindex
exec slg mcp serve --transport "$TRANSPORT" --workspace "$WORKSPACE" --host "$HOST" --port "$PORT" --dsn "$DSN"
