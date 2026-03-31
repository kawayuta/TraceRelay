from __future__ import annotations

import site
import sys


def _sanitize_user_site() -> None:
    user_sites = site.getusersitepackages()
    if isinstance(user_sites, str):
        blocked = {user_sites}
    else:
        blocked = set(user_sites)

    sys.path[:] = [
        path
        for path in sys.path
        if path not in blocked
        and not ("/Library/Python/" in path and path.endswith("site-packages"))
    ]


_sanitize_user_site()
