#!/bin/zsh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_PLUGIN_DIR="$REPO_ROOT/plugins/tracerelay"
HOME_PLUGIN_ROOT="$HOME/plugins"
HOME_PLUGIN_DIR="$HOME_PLUGIN_ROOT/tracerelay"
LEGACY_HOME_PLUGIN_DIR="$HOME_PLUGIN_ROOT/schemaledger"
HOME_MARKETPLACE_DIR="$HOME/.agents/plugins"
HOME_MARKETPLACE="$HOME_MARKETPLACE_DIR/marketplace.json"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  . "$REPO_ROOT/.env"
  set +a
fi

PLUGIN_MCP_URL="${TRACERELAY_PLUGIN_MCP_URL:-http://127.0.0.1:5064/mcp}"

mkdir -p "$HOME_PLUGIN_ROOT" "$HOME_MARKETPLACE_DIR"
rm -rf "$LEGACY_HOME_PLUGIN_DIR"
rm -rf "$HOME_PLUGIN_DIR"
cp -R "$SRC_PLUGIN_DIR" "$HOME_PLUGIN_DIR"
mkdir -p "$HOME_PLUGIN_DIR/.codex-plugin"

cat > "$HOME_PLUGIN_DIR/.codex-plugin/mcp.json" <<EOF
{
  "mcpServers": {
    "TraceRelay": {
      "type": "http",
      "url": "$PLUGIN_MCP_URL"
    }
  }
}
EOF

python3 - <<'PY' "$HOME_MARKETPLACE"
import json
import sys
from pathlib import Path

marketplace_path = Path(sys.argv[1])
entry = {
    "name": "tracerelay",
    "source": {
        "source": "local",
        "path": "./plugins/tracerelay",
    },
    "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    },
    "category": "Coding",
}

if marketplace_path.exists():
    data = json.loads(marketplace_path.read_text(encoding="utf-8"))
else:
    data = {
        "name": "local-home-plugins",
        "interface": {"displayName": "Local Home Plugins"},
        "plugins": [],
    }

plugins = [
    plugin
    for plugin in data.get("plugins", [])
    if plugin.get("name") not in {"tracerelay", "schemaledger"}
]
plugins.append(entry)
data["plugins"] = plugins

if "name" not in data:
    data["name"] = "local-home-plugins"
if "interface" not in data:
    data["interface"] = {"displayName": "Local Home Plugins"}
elif "displayName" not in data["interface"]:
    data["interface"]["displayName"] = "Local Home Plugins"

marketplace_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "Installed TraceRelay Codex plugin:"
echo "  plugin: $HOME_PLUGIN_DIR"
echo "  marketplace: $HOME_MARKETPLACE"
echo "  mcp: $HOME_PLUGIN_DIR/.codex-plugin/mcp.json"
