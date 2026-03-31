from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "schemaledger"


def test_plugin_manifest_has_expected_shape() -> None:
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "schemaledger"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["skills"] == "./skills/"
    assert "[TODO:" not in json.dumps(manifest)
    assert manifest["interface"]["displayName"] == "SchemaLedger"
    assert manifest["interface"]["composerIcon"] == "./assets/schemaledger-icon.svg"
    assert manifest["interface"]["screenshots"] == [
        "./assets/tasks-page.png",
        "./assets/google-trace-page.png",
    ]


def test_plugin_assets_exist() -> None:
    assert (PLUGIN_ROOT / "assets" / "schemaledger-icon.svg").exists()
    assert (PLUGIN_ROOT / "assets" / "tasks-page.png").exists()
    assert (PLUGIN_ROOT / "assets" / "google-trace-page.png").exists()


def test_plugin_mcp_config_uses_repo_local_stdio_server() -> None:
    config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
    server = config["mcpServers"]["schemaledger"]
    assert server["type"] == "stdio"
    assert server["command"] == "uv"
    assert "--project" in server["args"]
    assert "python" in server["args"]
    assert "-m" in server["args"]
    assert "schemaledger.mcp" in server["args"]
    assert server["env"]["PYTHONPATH"] == "../../src:../.."
    assert server["env"]["SCHEMALEDGER_LLM_PROVIDER"] == "lmstudio"
    assert server["env"]["SCHEMALEDGER_EMBEDDING_PROVIDER"] == "lmstudio"
    assert server["env"]["SCHEMALEDGER_LM_STUDIO_BASE_URL"] == "http://127.0.0.1:1234"
    assert server["env"]["SCHEMALEDGER_OLLAMA_BASE_URL"] == "http://127.0.0.1:11434"
    assert server["env"]["SCHEMALEDGER_OPENAI_BASE_URL"] == "https://api.openai.com"
    assert server["env"]["SCHEMALEDGER_GEMINI_BASE_URL"] == "https://generativelanguage.googleapis.com"
    assert server["env"]["SCHEMALEDGER_POSTGRES_DSN"].endswith("/schemaledger_fresh")


def test_marketplace_registers_repo_local_plugin() -> None:
    marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert marketplace["name"] == "local-repo-plugins"
    entry = marketplace["plugins"][0]
    assert entry["name"] == "schemaledger"
    assert entry["source"]["path"] == "./plugins/schemaledger"
    assert entry["policy"]["installation"] == "AVAILABLE"
    assert entry["policy"]["authentication"] == "ON_INSTALL"


def test_home_local_installer_script_exists() -> None:
    script = ROOT / "scripts" / "install_codex_plugin.sh"
    content = script.read_text()
    assert script.exists()
    assert "HOME_PLUGIN_DIR" in content
    assert "marketplace.json" in content
    assert "schemaledger.mcp" in content
    assert "SCHEMALEDGER_LLM_PROVIDER" in content
    assert "SCHEMALEDGER_OPENAI_API_KEY" in content
    assert "SCHEMALEDGER_GEMINI_API_KEY" in content
