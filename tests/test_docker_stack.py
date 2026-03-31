from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_db_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "schemaledger.db", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Apply SchemaLedger PostgreSQL schema" in result.stdout


def test_docker_start_web_script_declares_schema_apply_and_web_server() -> None:
    script = (ROOT / "scripts" / "docker_start_web.sh").read_text(encoding="utf-8")
    assert "slg db apply-schema" in script
    assert "--reindex" in script
    assert "slg web serve" in script


def test_docker_start_mcp_script_declares_schema_apply_and_mcp_server() -> None:
    script = (ROOT / "scripts" / "docker_start_mcp.sh").read_text(encoding="utf-8")
    assert "slg db apply-schema" in script
    assert "--reindex" in script
    assert "slg mcp serve" in script
    assert "SCHEMALEDGER_MCP_TRANSPORT" in script


def test_compose_includes_postgres_web_and_mcp_services() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "postgres:" in compose
    assert "web:" in compose
    assert "mcp:" in compose
    assert "condition: service_healthy" in compose
    assert "./workspace:/app/workspace" in compose
    assert '"5080:5080"' in compose
    assert '"5064:5063"' in compose
    assert "host.docker.internal:host-gateway" in compose
