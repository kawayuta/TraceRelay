from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "tracerelay"


def test_plugin_manifest_has_expected_shape() -> None:
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "tracerelay"
    assert manifest["mcpServers"] == "./.codex-plugin/mcp.json"
    assert manifest["skills"] == "./skills/"
    assert "[TODO:" not in json.dumps(manifest)
    assert manifest["interface"]["displayName"] == "TraceRelay"
    assert manifest["interface"]["composerIcon"] == "./assets/tracerelay-icon.svg"
    assert "plan_next_step" in json.dumps(manifest["interface"]["defaultPrompt"])
    assert "prepare_search_queries" in json.dumps(manifest["interface"]["defaultPrompt"])
    assert manifest["interface"]["screenshots"] == [
        "./assets/tasks-page.png",
        "./assets/google-trace-page.png",
    ]


def test_plugin_assets_exist() -> None:
    assert (PLUGIN_ROOT / "assets" / "tracerelay-icon.svg").exists()
    assert (PLUGIN_ROOT / "assets" / "tasks-page.png").exists()
    assert (PLUGIN_ROOT / "assets" / "google-trace-page.png").exists()


def test_plugin_skills_exist_and_cover_auto_routing() -> None:
    use_skill = (PLUGIN_ROOT / "skills" / "use-tracerelay" / "SKILL.md").read_text()
    routing_skill = (PLUGIN_ROOT / "skills" / "task-evolution-memory" / "SKILL.md").read_text()
    continue_skill = (PLUGIN_ROOT / "skills" / "continue-prior-work" / "SKILL.md").read_text()
    changed_skill = (PLUGIN_ROOT / "skills" / "what-changed" / "SKILL.md").read_text()
    structure_skill = (PLUGIN_ROOT / "skills" / "structure-this" / "SKILL.md").read_text()
    assert "Do not wait for the user to name the tools explicitly" in use_skill
    assert "plan_next_step" in use_skill
    assert "prepare_search_queries" in use_skill
    assert "continue what we learned" in routing_skill
    assert "pick up where we left off" in continue_skill
    assert "what changed" in changed_skill
    assert "family_revised" in changed_skill
    assert "structure this" in structure_skill


def test_plugin_skills_have_openai_agent_metadata() -> None:
    skill_roots = [
        PLUGIN_ROOT / "skills" / "use-tracerelay",
        PLUGIN_ROOT / "skills" / "task-evolution-memory",
        PLUGIN_ROOT / "skills" / "continue-prior-work",
        PLUGIN_ROOT / "skills" / "what-changed",
        PLUGIN_ROOT / "skills" / "structure-this",
    ]
    for skill_root in skill_roots:
        metadata = (skill_root / "agents" / "openai.yaml").read_text()
        assert 'value: "TraceRelay"' in metadata
        assert "default_prompt:" in metadata


def test_plugin_mcp_config_uses_repo_local_stdio_server() -> None:
    config = json.loads((PLUGIN_ROOT / ".codex-plugin" / "mcp.json").read_text())
    server = config["mcpServers"]["TraceRelay"]
    assert server["type"] == "http"
    assert server["url"] == "${TRACERELAY_PLUGIN_MCP_URL:-http://127.0.0.1:5064/mcp}"


def test_marketplace_registers_repo_local_plugin() -> None:
    marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert marketplace["name"] == "local-repo-plugins"
    entry = marketplace["plugins"][0]
    assert entry["name"] == "tracerelay"
    assert entry["source"]["path"] == "./plugins/tracerelay"
    assert entry["policy"]["installation"] == "AVAILABLE"
    assert entry["policy"]["authentication"] == "ON_INSTALL"


def test_home_local_installer_script_exists() -> None:
    script = ROOT / "scripts" / "install_codex_plugin.sh"
    content = script.read_text()
    assert script.exists()
    assert "HOME_PLUGIN_DIR" in content
    assert "marketplace.json" in content
    assert '.codex-plugin/mcp.json' in content
    assert "TRACERELAY_PLUGIN_MCP_URL" in content
    assert '. "$REPO_ROOT/.env"' in content
    assert '"TraceRelay"' in content
