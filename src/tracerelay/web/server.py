from __future__ import annotations

import argparse

from ..config import postgres_dsn_from_env
from .app import create_app
from .repository import PostgresTaskRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TraceRelay Flask web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5080)
    parser.add_argument("--dsn", default=postgres_dsn_from_env())
    args = parser.parse_args()

    app = create_app(PostgresTaskRepository(dsn=args.dsn))
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
