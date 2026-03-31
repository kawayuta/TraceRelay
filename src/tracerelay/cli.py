from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="trr",
        description="TraceRelay CLI.",
    )
    subparsers = parser.add_subparsers(dest="command")

    db_parser = subparsers.add_parser("db", help="Database operations.")
    db_subparsers = db_parser.add_subparsers(dest="db_command")
    db_apply = db_subparsers.add_parser(
        "apply-schema",
        help="Apply PostgreSQL schema and optionally reindex artifacts.",
    )
    db_apply.add_argument("--workspace", default="./workspace")
    db_apply.add_argument("--dsn")
    db_apply.add_argument("--reindex", action="store_true")
    db_apply.add_argument("--json", action="store_true")

    web_parser = subparsers.add_parser("web", help="Web UI operations.")
    web_subparsers = web_parser.add_subparsers(dest="web_command")
    web_serve = web_subparsers.add_parser("serve", help="Run the Flask web UI.")
    web_serve.add_argument("--host", default="127.0.0.1")
    web_serve.add_argument("--port", type=int, default=5080)
    web_serve.add_argument("--dsn")

    mcp_parser = subparsers.add_parser("mcp", help="MCP server operations.")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command")
    mcp_serve = mcp_subparsers.add_parser("serve", help="Run the MCP server.")
    mcp_serve.add_argument("--workspace", default="./workspace")
    mcp_serve.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
    )
    mcp_serve.add_argument("--host", default="127.0.0.1")
    mcp_serve.add_argument("--port", type=int, default=8000)
    mcp_serve.add_argument("--dsn")

    args = parser.parse_args()

    if args.command == "db" and args.db_command == "apply-schema":
        from .config import postgres_dsn_from_env
        from .db import main as db_main

        sys.argv = [
            "trr db apply-schema",
            "--workspace",
            args.workspace,
            "--dsn",
            args.dsn or postgres_dsn_from_env(),
            *(["--reindex"] if args.reindex else []),
            *(["--json"] if args.json else []),
        ]
        db_main()
        return

    if args.command == "web" and args.web_command == "serve":
        from .config import postgres_dsn_from_env
        from .web.server import main as web_main

        sys.argv = [
            "trr web serve",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--dsn",
            args.dsn or postgres_dsn_from_env(),
        ]
        web_main()
        return

    if args.command == "mcp" and args.mcp_command == "serve":
        from .config import postgres_dsn_from_env
        from .mcp.server import main as mcp_main

        sys.argv = [
            "trr mcp serve",
            "--workspace",
            args.workspace,
            "--transport",
            args.transport,
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--dsn",
            args.dsn or postgres_dsn_from_env(),
        ]
        mcp_main()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
