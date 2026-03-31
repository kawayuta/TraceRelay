from __future__ import annotations

import argparse
import json
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

from ..config import postgres_dsn_from_env
from ..llm import llm_from_env
from ..task_flow import JsonlArtifactStore
from ..task_runtime import TaskRuntime
from ..web.repository import PostgresTaskRepository, TaskBrowseRepository
from .prompts import register_prompts
from .resources import register_resources
from .tools import MCPToolbox, default_repository, default_sync_dsn, register_tools


def create_mcp_server(
    runtime: TaskRuntime,
    store: JsonlArtifactStore,
    repository: TaskBrowseRepository | None = None,
    *,
    sync_dsn: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    active_repository = repository or default_repository()
    toolbox = MCPToolbox(
        runtime=runtime,
        store=store,
        repository=active_repository,
        sync_dsn=default_sync_dsn(active_repository, sync_dsn),
    )
    server = FastMCP(
        name="TraceRelay",
        instructions=(
            "Task-first TraceRelay MCP server. "
            "Use tools to evolve tasks, inspect task lineage, and recall memory snapshots."
        ),
        host=host,
        port=port,
        json_response=True,
        stateless_http=True,
        streamable_http_path="/mcp",
    )
    register_tools(server, toolbox)
    register_resources(server, active_repository)
    register_prompts(server)
    return server


class TraceRelayMCPServer:
    def __init__(
        self,
        runtime: TaskRuntime,
        store: JsonlArtifactStore,
        repository: TaskBrowseRepository | None = None,
        *,
        sync_dsn: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        self.runtime = runtime
        self.store = store
        self.repository = repository or default_repository()
        self.sync_dsn = default_sync_dsn(self.repository, sync_dsn)
        self.fastmcp = create_mcp_server(
            runtime,
            store,
            self.repository,
            sync_dsn=self.sync_dsn,
            host=host,
            port=port,
        )

    def describe(self) -> dict[str, object]:
        tools = self.list_tools()
        resources = self.list_resources()
        resource_templates = self.list_resource_templates()
        prompts = self.list_prompts()
        return {
            "name": self.fastmcp.name,
            "tools": [
                {"name": tool.name, "description": tool.description}
                for tool in tools
            ],
            "resources": [
                {"uri": resource.uri, "name": resource.name, "description": resource.description}
                for resource in resources
            ]
            + [
                {
                    "uri": resource.uriTemplate,
                    "name": resource.name,
                    "description": resource.description,
                }
                for resource in resource_templates
            ],
            "prompts": [
                {
                    "name": prompt.name,
                    "description": prompt.description,
                    "arguments": [
                        argument.name
                        for argument in (prompt.arguments or [])
                    ],
                }
                for prompt in prompts
            ],
        }

    def list_tools(self) -> object:
        return anyio.run(self.fastmcp.list_tools)

    def list_resources(self) -> object:
        return anyio.run(self.fastmcp.list_resources)

    def list_resource_templates(self) -> object:
        return anyio.run(self.fastmcp.list_resource_templates)

    def list_prompts(self) -> object:
        return anyio.run(self.fastmcp.list_prompts)

    def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        result = anyio.run(self.fastmcp.call_tool, name, arguments)
        return _normalize_tool_result(result)

    def read_resource(self, uri: str) -> object:
        result = anyio.run(self.fastmcp.read_resource, uri)
        contents = list(result)
        if len(contents) == 1:
            return _decode_resource_content(contents[0].content)
        return [_decode_resource_content(item.content) for item in contents]

    def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> object:
        return anyio.run(self.fastmcp.get_prompt, name, arguments)

    def render_prompt(self, name: str, arguments: dict[str, str]) -> str:
        prompt = self.get_prompt(name, arguments)
        messages = prompt.messages
        if len(messages) == 1:
            content = getattr(messages[0], "content", None)
            if getattr(content, "type", None) == "text":
                return str(getattr(content, "text", ""))
        return json.dumps(messages, ensure_ascii=False)

    def run(self, transport: str = "stdio") -> None:
        self.fastmcp.run(transport=transport)


LocalMCPServer = TraceRelayMCPServer


def build_runtime_from_env(workspace: str) -> tuple[TaskRuntime, JsonlArtifactStore]:
    llm = llm_from_env()
    if llm is None:
        raise RuntimeError(
            "LLM environment is required to run the MCP server. "
            "Configure TRACERELAY_LLM_PROVIDER with LM Studio, Ollama, OpenAI, or Gemini settings."
        )
    store = JsonlArtifactStore(workspace)
    return TaskRuntime(llm=llm, artifact_store=store), store


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TraceRelay MCP server.")
    parser.add_argument("--workspace", default="./workspace")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dsn", default=postgres_dsn_from_env())
    args = parser.parse_args()

    runtime, store = build_runtime_from_env(args.workspace)
    repository = PostgresTaskRepository(dsn=args.dsn)
    server = TraceRelayMCPServer(
        runtime,
        store,
        repository=repository,
        sync_dsn=args.dsn,
        host=args.host,
        port=args.port,
    )
    server.run(transport=args.transport)


def _normalize_tool_result(result: object) -> object:
    if isinstance(result, tuple) and len(result) == 2:
        result = result[1]
    if isinstance(result, dict) and set(result.keys()) == {"result"}:
        return result["result"]
    return result


def _decode_resource_content(content: Any) -> object:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


if __name__ == "__main__":
    main()
