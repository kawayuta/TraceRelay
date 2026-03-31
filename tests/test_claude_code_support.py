from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "tracerelay"


def test_claude_plugin_manifest_has_expected_shape() -> None:
    manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "tracerelay"
    assert manifest["version"] == "0.1.0"
    assert "prior-work continuation" in manifest["description"]


def test_claude_marketplace_manifest_references_local_plugin() -> None:
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert marketplace["name"] == "tracerelay-local"
    plugin = marketplace["plugins"][0]
    assert plugin["name"] == "tracerelay"
    assert plugin["source"] == "./plugins/tracerelay"
    assert plugin["category"] == "development"


def test_claude_plugin_mcp_config_uses_direct_server_mapping() -> None:
    config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = config["TraceRelay"]
    assert server["type"] == "http"
    assert server["url"] == "${TRACERELAY_PLUGIN_MCP_URL:-http://127.0.0.1:5064/mcp}"


def test_claude_code_plugin_installer_uses_plugin_marketplace_flow() -> None:
    script = (ROOT / "scripts" / "install_claude_code_plugin.sh").read_text(encoding="utf-8")
    assert "claude plugin marketplace add" in script
    assert "claude plugin install" in script
    assert 'PLUGIN_NAME="tracerelay"' in script
    assert 'MARKETPLACE_NAME="tracerelay-local"' in script
    assert 'LEGACY_PLUGIN_NAME="schemaledger"' in script


def test_docs_and_env_example_are_tracerelay_branded() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "# TraceRelay" in readme
    assert "TRACERELAY_LLM_PROVIDER" in env_example
    assert "rerun the installer" in readme.lower()


def test_claude_plugin_shares_generic_routing_skills() -> None:
    plugin_readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    continue_skill = (PLUGIN_ROOT / "skills" / "continue-prior-work" / "SKILL.md").read_text(encoding="utf-8")
    changed_skill = (PLUGIN_ROOT / "skills" / "what-changed" / "SKILL.md").read_text(encoding="utf-8")
    structure_skill = (PLUGIN_ROOT / "skills" / "structure-this" / "SKILL.md").read_text(encoding="utf-8")
    assert "Natural prompts that should route well in Claude Code" in plugin_readme
    assert "continue this investigation" in continue_skill
    assert "what changed" in changed_skill
    assert "structure this" in structure_skill
