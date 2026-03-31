from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    src_dir = Path(__file__).resolve().parent
    project_root = src_dir.parent
    sys.path.insert(0, str(src_dir))
    sys.path.insert(0, str(project_root))

    from tracerelay.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
