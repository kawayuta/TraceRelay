from __future__ import annotations

import site
import sys
from pathlib import Path


_PKG_DIR = Path(__file__).resolve().parents[1] / "src" / "schemaledger"
_USER_SITES = site.getusersitepackages()

if isinstance(_USER_SITES, str):
    _USER_SITE_PATHS = {_USER_SITES}
else:
    _USER_SITE_PATHS = set(_USER_SITES)

sys.path[:] = [
    path
    for path in sys.path
    if path not in _USER_SITE_PATHS
    and not ("/Library/Python/" in path and path.endswith("site-packages"))
]
__file__ = str(_PKG_DIR / "__init__.py")
__path__ = [str(_PKG_DIR)]

with open(__file__, "r", encoding="utf-8") as handle:
    exec(compile(handle.read(), __file__, "exec"), globals(), globals())
