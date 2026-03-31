#!/bin/sh

set -eu

WORKSPACE="${TRACERELAY_WORKSPACE:-/app/workspace}"
DSN="${TRACERELAY_POSTGRES_DSN:-postgresql://postgres:postgres@postgres:5432/tracerelay_fresh}"
HOST="${TRACERELAY_MCP_HOST:-0.0.0.0}"
PORT="${TRACERELAY_MCP_PORT:-5063}"
TRANSPORT="${TRACERELAY_MCP_TRANSPORT:-sse}"

trr db apply-schema --workspace "$WORKSPACE" --dsn "$DSN" --reindex
exec trr mcp serve --transport "$TRANSPORT" --workspace "$WORKSPACE" --host "$HOST" --port "$PORT" --dsn "$DSN"
