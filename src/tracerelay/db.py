from __future__ import annotations

import argparse
import json

import psycopg

from .config import postgres_dsn_from_env
from .indexer.loader import TaskRuntimeProjector
from .task_flow import JsonlArtifactStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply TraceRelay PostgreSQL schema and optionally reindex artifacts.")
    parser.add_argument("--workspace", default="./workspace")
    parser.add_argument("--dsn", default=postgres_dsn_from_env())
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    store = JsonlArtifactStore(args.workspace)
    projector = TaskRuntimeProjector(store)

    with psycopg.connect(args.dsn) as connection:
        projector.apply_schema(connection)
        if args.reindex:
            projector.reindex(connection)

    result = {
        "workspace": str(store.root),
        "dsn": args.dsn,
        "reindexed": bool(args.reindex),
        "task_count": len(store.list_task_ids()),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return
    print(
        "Applied TraceRelay schema to PostgreSQL"
        f" dsn={args.dsn} workspace={store.root} reindex={args.reindex}"
    )


if __name__ == "__main__":
    main()
