from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..memory import normalize_subject
from ..action_planning import (
    build_information_gap_analysis,
    build_next_step_plan,
    build_search_query_plan,
)
from ..web.repository import TaskBrowseRepository


def list_resources() -> list[dict[str, object]]:
    return [
        {"uri": "tracerelay://tasks", "name": "tasks", "description": "List task summaries"},
        {"uri": "tracerelay://tasks/{task_id}", "name": "task", "description": "Read task detail"},
        {
            "uri": "tracerelay://tasks/{task_id}/subject-graph",
            "name": "subject_graph",
            "description": "Read the task subject graph, branch plan, and branch bundle",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/task-relations",
            "name": "task_relations",
            "description": "Read persisted parent/child task relations for the task",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/coverage",
            "name": "coverage",
            "description": "Read task coverage",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/schema",
            "name": "schema",
            "description": "Read task schema lineage",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/events",
            "name": "events",
            "description": "Read task events",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/trace",
            "name": "trace",
            "description": "Read task flowchart and decision trace",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/gaps",
            "name": "gaps",
            "description": "Read information gaps for the task",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/queries",
            "name": "queries",
            "description": "Read recommended search queries for the task",
        },
        {
            "uri": "tracerelay://tasks/{task_id}/next-step",
            "name": "next_step",
            "description": "Read the recommended next actions for the task",
        },
        {"uri": "tracerelay://memory/profile", "name": "memory_profile", "description": "Read workspace profile memory"},
        {
            "uri": "tracerelay://memory/profile/{profile_id}",
            "name": "memory_profile_named",
            "description": "Read named profile memory",
        },
        {
            "uri": "tracerelay://memory/subjects/{subject}",
            "name": "subject_memory",
            "description": "Read subject memory",
        },
        {
            "uri": "tracerelay://memory/subjects/{subject}/relations",
            "name": "subject_relations",
            "description": "Read persisted subject graph relations touching the subject or scope",
        },
        {
            "uri": "tracerelay://memory/tasks/{task_id}",
            "name": "task_memory_context",
            "description": "Read task memory context",
        },
        {
            "uri": "tracerelay://memory/search/{query}",
            "name": "memory_search",
            "description": "Search prior tasks and learned facts",
        },
    ]


def register_resources(mcp: FastMCP, repository: TaskBrowseRepository) -> None:
    @mcp.resource(
        "tracerelay://tasks",
        name="tasks",
        description="List task summaries",
        mime_type="application/json",
    )
    def tasks() -> list[dict[str, object]]:
        return repository.list_tasks()

    @mcp.resource(
        "tracerelay://tasks/{task_id}",
        name="task",
        description="Read task detail",
        mime_type="application/json",
    )
    def task(task_id: str) -> dict[str, object]:
        return repository.get_task(task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/subject-graph",
        name="subject_graph",
        description="Read the task subject graph, branch plan, and branch bundle",
        mime_type="application/json",
    )
    def subject_graph(task_id: str) -> dict[str, object]:
        return _build_task_subject_graph(repository, task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/task-relations",
        name="task_relations",
        description="Read persisted parent/child task relations for the task",
        mime_type="application/json",
    )
    def task_relations(task_id: str) -> dict[str, object]:
        task = repository.get_task(task_id)
        return {
            "task_id": task_id,
            "resolved_subject": str(dict(task.get("interpretation") or {}).get("resolved_subject", "")),
            "relations": repository.list_task_relations(task_id),
        }

    @mcp.resource(
        "tracerelay://tasks/{task_id}/coverage",
        name="coverage",
        description="Read task coverage",
        mime_type="application/json",
    )
    def coverage(task_id: str) -> dict[str, object]:
        return repository.get_task_coverage(task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/schema",
        name="schema",
        description="Read task schema lineage",
        mime_type="application/json",
    )
    def schema(task_id: str) -> dict[str, object]:
        return repository.get_task_schema(task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/events",
        name="events",
        description="Read task events",
        mime_type="application/json",
    )
    def events(task_id: str) -> list[dict[str, object]]:
        return repository.get_task_events(task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/trace",
        name="trace",
        description="Read task flowchart and decision trace",
        mime_type="application/json",
    )
    def trace(task_id: str) -> dict[str, object]:
        return repository.get_task_trace(task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/gaps",
        name="gaps",
        description="Read information gaps for the task",
        mime_type="application/json",
    )
    def gaps(task_id: str) -> dict[str, object]:
        return build_information_gap_analysis(repository, task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/queries",
        name="queries",
        description="Read recommended search queries for the task",
        mime_type="application/json",
    )
    def queries(task_id: str) -> dict[str, object]:
        return build_search_query_plan(repository, task_id)

    @mcp.resource(
        "tracerelay://tasks/{task_id}/next-step",
        name="next_step",
        description="Read the recommended next actions for the task",
        mime_type="application/json",
    )
    def next_step(task_id: str) -> dict[str, object]:
        return build_next_step_plan(repository, task_id)

    @mcp.resource(
        "tracerelay://memory/profile",
        name="memory_profile",
        description="Read workspace profile memory",
        mime_type="application/json",
    )
    def memory_profile() -> dict[str, object]:
        from ..web.app import build_workspace_profile_memory

        return build_workspace_profile_memory(repository)

    @mcp.resource(
        "tracerelay://memory/profile/{profile_id}",
        name="memory_profile_named",
        description="Read named profile memory",
        mime_type="application/json",
    )
    def memory_profile_named(profile_id: str) -> dict[str, object]:
        from ..web.app import build_workspace_profile_memory

        return build_workspace_profile_memory(repository, profile_id=profile_id)

    @mcp.resource(
        "tracerelay://memory/subjects/{subject}",
        name="subject_memory",
        description="Read subject memory",
        mime_type="application/json",
    )
    def subject_memory(subject: str) -> dict[str, object]:
        from ..web.app import build_subject_memory

        return build_subject_memory(repository, subject)

    @mcp.resource(
        "tracerelay://memory/subjects/{subject}/relations",
        name="subject_relations",
        description="Read persisted subject graph relations touching the subject or scope",
        mime_type="application/json",
    )
    def subject_relations(subject: str) -> dict[str, object]:
        return {
            "subject": subject,
            "subject_key": normalize_subject(subject),
            "relations": repository.list_subject_relations(subject),
        }

    @mcp.resource(
        "tracerelay://memory/tasks/{task_id}",
        name="task_memory_context",
        description="Read task memory context",
        mime_type="application/json",
    )
    def task_memory_context(task_id: str) -> dict[str, object]:
        from ..web.app import build_task_memory_context

        return build_task_memory_context(repository, task_id)

    @mcp.resource(
        "tracerelay://memory/search/{query}",
        name="memory_search",
        description="Search prior tasks and learned facts",
        mime_type="application/json",
    )
    def memory_search(query: str) -> dict[str, object]:
        from ..web.app import build_memory_search

        return build_memory_search(repository, query)


def _build_task_subject_graph(repository: TaskBrowseRepository, task_id: str) -> dict[str, object]:
    task = repository.get_task(task_id)
    interpretation = dict(task.get("interpretation") or {})
    subject_graph = dict(task.get("subject_graph") or {})
    scope_key = str(
        subject_graph.get("scope_key")
        or interpretation.get("scope_key")
        or interpretation.get("resolved_subject")
        or ""
    )
    return {
        "task_id": task_id,
        "resolved_subject": str(interpretation.get("resolved_subject", "")),
        "family": str(interpretation.get("family", "")),
        "scope_key": scope_key,
        "subject_graph": subject_graph,
        "branch_plan": task.get("branch_plan"),
        "branch_bundle": task.get("branch_bundle"),
        "task_relations": repository.list_task_relations(task_id),
        "subject_relations": repository.list_subject_relations(scope_key) if scope_key else [],
    }
