from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cli_module_help_mentions_trr() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tracerelay.cli", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "TraceRelay CLI." in result.stdout
    assert "trr" in result.stdout


def test_docker_scripts_use_trr_short_name() -> None:
    web_script = (ROOT / "scripts" / "docker_start_web.sh").read_text(encoding="utf-8")
    mcp_script = (ROOT / "scripts" / "docker_start_mcp.sh").read_text(encoding="utf-8")
    assert "trr db apply-schema" in web_script
    assert "trr web serve" in web_script
    assert "trr db apply-schema" in mcp_script
    assert "trr mcp serve" in mcp_script
