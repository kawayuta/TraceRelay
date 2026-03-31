from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cli_module_help_mentions_slg() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "schemaledger.cli", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "SchemaLedger CLI." in result.stdout
    assert "slg" in result.stdout


def test_docker_scripts_use_slg_short_name() -> None:
    web_script = (ROOT / "scripts" / "docker_start_web.sh").read_text(encoding="utf-8")
    mcp_script = (ROOT / "scripts" / "docker_start_mcp.sh").read_text(encoding="utf-8")
    assert "slg db apply-schema" in web_script
    assert "slg web serve" in web_script
    assert "slg db apply-schema" in mcp_script
    assert "slg mcp serve" in mcp_script
