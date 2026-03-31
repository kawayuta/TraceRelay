#!/bin/sh

set -eu

WORKSPACE="${TRACERELAY_WORKSPACE:-/app/workspace}"
DSN="${TRACERELAY_POSTGRES_DSN:-postgresql://postgres:postgres@postgres:5432/tracerelay_fresh}"
HOST="${TRACERELAY_WEB_HOST:-0.0.0.0}"
PORT="${TRACERELAY_WEB_PORT:-5080}"

trr db apply-schema --workspace "$WORKSPACE" --dsn "$DSN" --reindex
exec trr web serve --host "$HOST" --port "$PORT" --dsn "$DSN"
