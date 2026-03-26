from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..web.repository import TaskBrowseRepository


def list_resources() -> list[dict[str, object]]:
    return [
        {"uri": "schemaledger://tasks", "name": "tasks", "description": "List task summaries"},
        {"uri": "schemaledger://tasks/{task_id}", "name": "task", "description": "Read task detail"},
        {
            "uri": "schemaledger://tasks/{task_id}/coverage",
            "name": "coverage",
            "description": "Read task coverage",
        },
        {
            "uri": "schemaledger://tasks/{task_id}/schema",
            "name": "schema",
            "description": "Read task schema lineage",
        },
        {
            "uri": "schemaledger://tasks/{task_id}/events",
            "name": "events",
            "description": "Read task events",
        },
        {
            "uri": "schemaledger://tasks/{task_id}/trace",
            "name": "trace",
            "description": "Read task flowchart and decision trace",
        },
    ]


def register_resources(mcp: FastMCP, repository: TaskBrowseRepository) -> None:
    @mcp.resource(
        "schemaledger://tasks",
        name="tasks",
        description="List task summaries",
        mime_type="application/json",
    )
    def tasks() -> list[dict[str, object]]:
        return repository.list_tasks()

    @mcp.resource(
        "schemaledger://tasks/{task_id}",
        name="task",
        description="Read task detail",
        mime_type="application/json",
    )
    def task(task_id: str) -> dict[str, object]:
        return repository.get_task(task_id)

    @mcp.resource(
        "schemaledger://tasks/{task_id}/coverage",
        name="coverage",
        description="Read task coverage",
        mime_type="application/json",
    )
    def coverage(task_id: str) -> dict[str, object]:
        return repository.get_task_coverage(task_id)

    @mcp.resource(
        "schemaledger://tasks/{task_id}/schema",
        name="schema",
        description="Read task schema lineage",
        mime_type="application/json",
    )
    def schema(task_id: str) -> dict[str, object]:
        return repository.get_task_schema(task_id)

    @mcp.resource(
        "schemaledger://tasks/{task_id}/events",
        name="events",
        description="Read task events",
        mime_type="application/json",
    )
    def events(task_id: str) -> list[dict[str, object]]:
        return repository.get_task_events(task_id)

    @mcp.resource(
        "schemaledger://tasks/{task_id}/trace",
        name="trace",
        description="Read task flowchart and decision trace",
        mime_type="application/json",
    )
    def trace(task_id: str) -> dict[str, object]:
        return repository.get_task_trace(task_id)
