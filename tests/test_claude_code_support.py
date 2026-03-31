from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_mcp_json_exposes_compose_sse_endpoint() -> None:
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert "mcpServers" in config
    if "schemaledger" in config["mcpServers"]:
        server = config["mcpServers"]["schemaledger"]
        assert server["type"] == "sse"
        assert server["url"] == "${SCHEMALEDGER_CLAUDE_MCP_URL:-http://127.0.0.1:5064/sse}"
    else:
        assert config["mcpServers"] == {}


def test_claude_code_installer_script_uses_official_cli_flow() -> None:
    script = (ROOT / "scripts" / "install_claude_code_mcp.sh").read_text(encoding="utf-8")
    assert "claude mcp add --transport sse --scope user schemaledger" in script
    assert "claude mcp get schemaledger" in script
    assert "SCHEMALEDGER_CLAUDE_MCP_URL" in script
