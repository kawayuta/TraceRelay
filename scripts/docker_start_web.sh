#!/bin/sh

set -eu

WORKSPACE="${SCHEMALEDGER_WORKSPACE:-/app/workspace}"
DSN="${SCHEMALEDGER_POSTGRES_DSN:-postgresql://postgres:postgres@postgres:5432/schemaledger_fresh}"
HOST="${SCHEMALEDGER_WEB_HOST:-0.0.0.0}"
PORT="${SCHEMALEDGER_WEB_PORT:-5080}"

slg db apply-schema --workspace "$WORKSPACE" --dsn "$DSN" --reindex
exec slg web serve --host "$HOST" --port "$PORT" --dsn "$DSN"
