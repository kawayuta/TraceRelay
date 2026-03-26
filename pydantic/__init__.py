from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USER_SITE_MARKER = "/Library/Python/"
sys.path[:] = [
    path
    for path in sys.path
    if not (USER_SITE_MARKER in path and path.endswith("site-packages"))
]

matches = sorted((ROOT / ".venv" / "lib").glob("python*/site-packages/pydantic"))
if not matches:
    raise ImportError("Could not find pydantic in the local .venv")

_PKG_DIR = matches[0]
__file__ = str(_PKG_DIR / "__init__.py")
__path__ = [str(_PKG_DIR)]

with open(__file__, "r", encoding="utf-8") as handle:
    exec(compile(handle.read(), __file__, "exec"), globals(), globals())
