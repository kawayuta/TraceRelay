from __future__ import annotations

__all__ = ["LocalMCPServer", "SchemaLedgerMCPServer", "create_mcp_server"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    from .server import LocalMCPServer, SchemaLedgerMCPServer, create_mcp_server

    exports = {
        "LocalMCPServer": LocalMCPServer,
        "SchemaLedgerMCPServer": SchemaLedgerMCPServer,
        "create_mcp_server": create_mcp_server,
    }
    return exports[name]
