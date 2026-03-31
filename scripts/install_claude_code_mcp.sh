#!/bin/sh

set -eu

if ! command -v claude >/dev/null 2>&1; then
  echo "Claude Code CLI ('claude') was not found in PATH." >&2
  exit 1
fi

MCP_URL="${SCHEMALEDGER_CLAUDE_MCP_URL:-http://127.0.0.1:5064/sse}"

claude mcp remove schemaledger >/dev/null 2>&1 || true
claude mcp add --transport sse --scope user schemaledger "$MCP_URL"

echo "Installed SchemaLedger MCP for Claude Code user scope:"
echo "  name: schemaledger"
echo "  url:  $MCP_URL"
echo
echo "Verify with:"
echo "  claude mcp get schemaledger"
