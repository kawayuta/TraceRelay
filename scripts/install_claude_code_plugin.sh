#!/bin/sh

set -eu

if ! command -v claude >/dev/null 2>&1; then
  echo "Claude Code CLI ('claude') was not found in PATH." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MARKETPLACE_SOURCE="$REPO_ROOT"
MARKETPLACE_NAME="tracerelay-local"
LEGACY_MARKETPLACE_NAME="schemaledger-local"
PLUGIN_NAME="tracerelay"
LEGACY_PLUGIN_NAME="schemaledger"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  . "$REPO_ROOT/.env"
  set +a
fi

claude mcp remove schemaledger -s user >/dev/null 2>&1 || true
claude plugin uninstall "$LEGACY_PLUGIN_NAME" >/dev/null 2>&1 || true
claude plugin marketplace remove "$MARKETPLACE_NAME" >/dev/null 2>&1 || true
claude plugin marketplace remove "$LEGACY_MARKETPLACE_NAME" >/dev/null 2>&1 || true
claude plugin marketplace add "$MARKETPLACE_SOURCE"

claude plugin uninstall "$PLUGIN_NAME" >/dev/null 2>&1 || true
claude plugin install "$PLUGIN_NAME@$MARKETPLACE_NAME"

echo "Installed TraceRelay Claude Code plugin:"
echo "  marketplace: $MARKETPLACE_NAME"
echo "  plugin:      $PLUGIN_NAME"
echo
echo "Verify with:"
echo "  claude plugin list"
