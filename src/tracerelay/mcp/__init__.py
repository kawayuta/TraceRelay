from __future__ import annotations

__all__ = ["LocalMCPServer", "TraceRelayMCPServer", "create_mcp_server"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    from .server import LocalMCPServer, TraceRelayMCPServer, create_mcp_server

    exports = {
        "LocalMCPServer": LocalMCPServer,
        "TraceRelayMCPServer": TraceRelayMCPServer,
        "create_mcp_server": create_mcp_server,
    }
    return exports[name]
