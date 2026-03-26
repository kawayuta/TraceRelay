from __future__ import annotations

import os


DEFAULT_POSTGRES_DSN = "postgresql://postgres:postgres@127.0.0.1:55432/schemaledger_fresh"


def postgres_dsn_from_env() -> str:
    return os.getenv("SCHEMALEDGER_POSTGRES_DSN", DEFAULT_POSTGRES_DSN)
