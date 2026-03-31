from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "schemaledger"


def test_claude_plugin_manifest_has_expected_shape() -> None:
    manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "schemaledger"
    assert manifest["version"] == "0.1.0"
    assert "self-evolving schema runtime" in manifest["description"]


def test_claude_marketplace_manifest_references_local_plugin() -> None:
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert marketplace["name"] == "schemaledger-local"
    plugin = marketplace["plugins"][0]
    assert plugin["name"] == "schemaledger"
    assert plugin["source"] == "./plugins/schemaledger"
    assert plugin["category"] == "development"


def test_claude_code_plugin_installer_uses_plugin_marketplace_flow() -> None:
    script = (ROOT / "scripts" / "install_claude_code_plugin.sh").read_text(encoding="utf-8")
    assert "claude plugin marketplace add" in script
    assert "claude plugin install" in script
    assert 'PLUGIN_NAME="schemaledger"' in script
    assert 'MARKETPLACE_NAME="schemaledger-local"' in script
