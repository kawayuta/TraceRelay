from __future__ import annotations

from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

from mcp.server.fastmcp import FastMCP

from ..config import postgres_dsn_from_env
from ..llm import LLMError
from ..indexer.loader import TaskRuntimeProjector
from ..evolution.ids import next_id
from ..models import ArtifactRecord
from ..task_runtime import TaskRuntime
from ..task_flow import JsonlArtifactStore
from ..web.app import build_memory_search, build_subject_memory, build_task_memory_context, build_workspace_profile_memory
from ..web.repository import PostgresTaskRepository, TaskBrowseRepository


def list_tools() -> list[dict[str, object]]:
    return [
        {"name": "task_evolve", "description": "Run the task-first runtime for a prompt."},
        {"name": "task_trace", "description": "Return the task flowchart and decision trace."},
        {"name": "schema_status", "description": "Return schema lineage for a task."},
        {"name": "schema_apply", "description": "Return the active schema after auto-apply evolution."},
        {"name": "artifact_read", "description": "Read artifacts for a task."},
        {"name": "artifact_search", "description": "Search tasks by prompt, subject, or family."},
        {"name": "memory_search", "description": "Vector-style search over prior tasks and learned facts."},
        {"name": "memory_profile", "description": "Read the workspace profile memory snapshot."},
        {"name": "subject_memory", "description": "Read subject memory and recalled learnings."},
        {"name": "task_memory_context", "description": "Read task memory context for follow-up prompts."},
    ]


class MCPToolbox:
    def __init__(
        self,
        runtime: TaskRuntime,
        store: JsonlArtifactStore,
        repository: TaskBrowseRepository,
        sync_dsn: str | None = None,
    ) -> None:
        self.runtime = runtime
        self.store = store
        self.repository = repository
        self.projector = TaskRuntimeProjector(store)
        self.sync_dsn = sync_dsn

    def call(self, name: str, arguments: dict[str, object]) -> object:
        if name == "task_evolve":
            prompt = str(arguments["prompt"])
            task_ids_before = set(self.store.list_task_ids())
            try:
                run = self.runtime.run_task(self.runtime_task_spec(prompt))
            except Exception as exc:
                task_id = self._finalize_failed_task(task_ids_before, exc)
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "reason": self._failure_reason(exc),
                    "error": str(exc),
                }
            self._sync_task(run.task_id)
            return {"task_id": run.task_id, "status": run.status, "reason": run.reason}
        if name == "task_trace":
            return self.repository.get_task_trace(str(arguments["task_id"]))
        if name == "schema_status":
            return self.repository.get_task_schema(str(arguments["task_id"]))
        if name == "schema_apply":
            return self._apply_schema(str(arguments["task_id"]))
        if name == "artifact_read":
            return self.repository.read_artifacts(
                str(arguments["task_id"]),
                str(arguments["artifact_type"]) if "artifact_type" in arguments else None,
            )
        if name == "artifact_search":
            return self.repository.search(str(arguments["query"]))
        if name == "memory_search":
            return build_memory_search(
                self.repository,
                str(arguments["query"]),
                limit=int(arguments.get("limit", 8)),
            )
        if name == "memory_profile":
            return build_workspace_profile_memory(
                self.repository,
                profile_id=str(arguments.get("profile_id", "workspace")),
            )
        if name == "subject_memory":
            return build_subject_memory(
                self.repository,
                str(arguments["subject"]),
                limit=int(arguments.get("limit", 6)),
            )
        if name == "task_memory_context":
            return build_task_memory_context(
                self.repository,
                str(arguments["task_id"]),
                limit=int(arguments.get("limit", 6)),
            )
        raise KeyError(name)

    def runtime_task_spec(self, prompt: str):
        from ..models import TaskSpec

        return TaskSpec(prompt=prompt)

    def _apply_schema(self, task_id: str) -> dict[str, object]:
        schema = self.repository.get_task_schema(task_id)
        active_schema = schema.get("active_schema")
        candidate = schema.get("candidate")
        if active_schema is None:
            return {"task_id": task_id, "applied": False, "reason": "no_active_schema"}
        artifact = ArtifactRecord(
            artifact_id=next_id("artifact"),
            task_id=task_id,
            artifact_type="task_event",
            payload={
                "event_id": next_id("event"),
                "kind": "schema_apply_confirmed",
                "details": {
                    "candidate_id": None if candidate is None else candidate.get("candidate_id"),
                    "schema_id": active_schema["schema_id"],
                    "version": active_schema["version"],
                },
            },
        )
        self.store.append(artifact)
        self._sync_task(task_id)
        return {
            "task_id": task_id,
            "applied": True,
            "schema_id": active_schema["schema_id"],
            "version": active_schema["version"],
        }

    def _sync_task(self, task_id: str) -> None:
        if self.sync_dsn is None:
            return
        if psycopg is None:  # pragma: no cover
            raise RuntimeError("psycopg is required for PostgreSQL MCP sync")
        with psycopg.connect(self.sync_dsn) as connection:
            self.projector.apply_schema(connection)
            self.projector.sync_task(connection, task_id)

    def _finalize_failed_task(self, task_ids_before: set[str], exc: Exception) -> str:
        task_id = self._newest_task_id(task_ids_before) or next_id("task")
        existing_artifacts = list(self.store.list_for_task(task_id))
        if not existing_artifacts:
            self.store.append(
                ArtifactRecord(
                    artifact_id=next_id("artifact"),
                    task_id=task_id,
                    artifact_type="task_prompt",
                    payload={"prompt": "", "locale": "auto"},
                )
            )
            existing_artifacts = list(self.store.list_for_task(task_id))

        has_task_run = any(artifact.artifact_type == "task_run" for artifact in existing_artifacts)
        if not any(
            artifact.artifact_type == "task_event"
            and artifact.payload.get("kind") == "task_failed"
            for artifact in existing_artifacts
        ):
            self.store.append(
                ArtifactRecord(
                    artifact_id=next_id("artifact"),
                    task_id=task_id,
                    artifact_type="task_event",
                    payload={
                        "event_id": next_id("event"),
                        "kind": "task_failed",
                        "details": {
                            "reason": self._failure_reason(exc),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    },
                )
            )
        if not has_task_run:
            self.store.append(
                ArtifactRecord(
                    artifact_id=next_id("artifact"),
                    task_id=task_id,
                    artifact_type="task_run",
                    payload={
                        "family": "",
                        "schema_id": "",
                        "schema_version": 0,
                        "status": "failed",
                        "reason": self._failure_reason(exc),
                        "attempts": 0,
                        "schema_rounds": 0,
                        "error": str(exc),
                    },
                )
            )
        self._sync_task(task_id)
        return task_id

    def _newest_task_id(self, task_ids_before: set[str]) -> str | None:
        candidates = [task_id for task_id in self.store.list_task_ids() if task_id not in task_ids_before]
        if not candidates:
            return None
        return candidates[-1]

    def _failure_reason(self, exc: Exception) -> str:
        if isinstance(exc, LLMError):
            return "llm_error"
        return "runtime_exception"


def default_repository() -> PostgresTaskRepository:
    return PostgresTaskRepository(dsn=postgres_dsn_from_env())


def default_sync_dsn(repository: TaskBrowseRepository, sync_dsn: str | None = None) -> str | None:
    if sync_dsn is not None:
        return sync_dsn
    if isinstance(repository, PostgresTaskRepository):
        return repository.dsn
    return None


def register_tools(mcp: FastMCP, toolbox: MCPToolbox) -> None:
    @mcp.tool(
        name="task_evolve",
        description="Run the task-first runtime for a prompt.",
    )
    def task_evolve(prompt: str) -> dict[str, object]:
        return dict(toolbox.call("task_evolve", {"prompt": prompt}))

    @mcp.tool(
        name="task_trace",
        description="Return the task flowchart and decision trace.",
    )
    def task_trace(task_id: str) -> dict[str, object]:
        return dict(toolbox.call("task_trace", {"task_id": task_id}))

    @mcp.tool(
        name="schema_status",
        description="Return schema lineage for a task.",
    )
    def schema_status(task_id: str) -> dict[str, object]:
        return dict(toolbox.call("schema_status", {"task_id": task_id}))

    @mcp.tool(
        name="schema_apply",
        description="Return the active schema after auto-apply evolution.",
    )
    def schema_apply(task_id: str) -> dict[str, object]:
        return dict(toolbox.call("schema_apply", {"task_id": task_id}))

    @mcp.tool(
        name="artifact_read",
        description="Read artifacts for a task.",
    )
    def artifact_read(task_id: str, artifact_type: str | None = None) -> list[dict[str, object]]:
        return list(
            toolbox.call(
                "artifact_read",
                {
                    "task_id": task_id,
                    **({"artifact_type": artifact_type} if artifact_type is not None else {}),
                },
            )
        )

    @mcp.tool(
        name="artifact_search",
        description="Search tasks by prompt, subject, or family.",
    )
    def artifact_search(query: str) -> list[dict[str, object]]:
        return list(toolbox.call("artifact_search", {"query": query}))

    @mcp.tool(
        name="memory_search",
        description="Vector-style search over prior tasks and learned facts.",
    )
    def memory_search(query: str, limit: int = 8) -> dict[str, object]:
        return dict(toolbox.call("memory_search", {"query": query, "limit": limit}))

    @mcp.tool(
        name="memory_profile",
        description="Read the workspace profile memory snapshot.",
    )
    def memory_profile(profile_id: str = "workspace") -> dict[str, object]:
        return dict(toolbox.call("memory_profile", {"profile_id": profile_id}))

    @mcp.tool(
        name="subject_memory",
        description="Read subject memory and recalled learnings.",
    )
    def subject_memory(subject: str, limit: int = 6) -> dict[str, object]:
        return dict(toolbox.call("subject_memory", {"subject": subject, "limit": limit}))

    @mcp.tool(
        name="task_memory_context",
        description="Read task memory context for follow-up prompts.",
    )
    def task_memory_context(task_id: str, limit: int = 6) -> dict[str, object]:
        return dict(toolbox.call("task_memory_context", {"task_id": task_id, "limit": limit}))
