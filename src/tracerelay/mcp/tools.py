from __future__ import annotations

import logging
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

from mcp.server.fastmcp import FastMCP

from ..action_planning import (
    build_information_gap_analysis,
    build_next_step_plan,
    build_search_query_plan,
    build_subject_bootstrap_plan,
)
from ..config import postgres_dsn_from_env
from ..llm import LLMError
from ..indexer.loader import TaskRuntimeProjector
from ..evolution.ids import next_id
from ..memory import normalize_subject
from ..models import ArtifactRecord
from ..task_runtime import TaskRuntime
from ..task_flow import JsonlArtifactStore
from ..web.app import build_memory_search, build_subject_memory, build_task_memory_context, build_workspace_profile_memory
from ..web.repository import PostgresTaskRepository, TaskBrowseRepository

logger = logging.getLogger("tracerelay.mcp")
logger.setLevel(logging.INFO)


def list_tools() -> list[dict[str, object]]:
    return [
        {"name": "task_evolve", "description": "Run the task-first runtime for a prompt."},
        {
            "name": "continue_prior_work",
            "description": "Continue earlier work on the same subject, reuse prior memory, and run the next structured step.",
        },
        {
            "name": "structure_subject",
            "description": "Turn a natural-language research or analysis request into structured fields, schema evolution, and traceable output.",
        },
        {
            "name": "inspect_latest_changes",
            "description": "Inspect what changed in the latest run, including retries, family rechecks, and schema updates.",
        },
        {"name": "task_trace", "description": "Return the task flowchart and decision trace."},
        {"name": "schema_status", "description": "Return schema lineage for a task."},
        {"name": "schema_apply", "description": "Return the active schema after auto-apply evolution."},
        {"name": "artifact_read", "description": "Read artifacts for a task."},
        {"name": "artifact_search", "description": "Search tasks by prompt, subject, or family."},
        {"name": "memory_search", "description": "Vector-style search over prior tasks and learned facts."},
        {"name": "memory_profile", "description": "Read the workspace profile memory snapshot."},
        {"name": "subject_memory", "description": "Read subject memory and recalled learnings."},
        {"name": "task_memory_context", "description": "Read task memory context for follow-up prompts."},
        {
            "name": "analyze_information_gaps",
            "description": "Explain which values, fields, or relations are still missing and what is already known.",
        },
        {
            "name": "prepare_search_queries",
            "description": "Generate narrow search queries based on the current gaps, known facts, and active schema.",
        },
        {
            "name": "plan_next_step",
            "description": "Recommend the next TraceRelay action, pre-search checks, and targeted queries before generic search.",
        },
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
        logger.info("TraceRelay MCP tool start name=%s args=%s", name, _summarize_arguments(arguments))
        if name == "task_evolve":
            prompt = str(arguments["prompt"])
            task_ids_before = set(self.store.list_task_ids())
            try:
                run = self.runtime.run_task(self.runtime_task_spec(prompt))
            except Exception as exc:
                task_id = self._finalize_failed_task(task_ids_before, exc)
                result = {
                    "task_id": task_id,
                    "status": "failed",
                    "reason": self._failure_reason(exc),
                    "error": str(exc),
                }
                logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
                return result
            self._sync_task(run.task_id)
            result = {"task_id": run.task_id, "status": run.status, "reason": run.reason}
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "continue_prior_work":
            prompt = str(arguments["prompt"])
            subject = _optional_string(arguments.get("subject"))
            limit = int(arguments.get("limit", 6))
            recall = (
                build_subject_memory(self.repository, subject, limit=limit)
                if subject
                else build_memory_search(self.repository, prompt, limit=limit)
            )
            run = dict(self.call("task_evolve", {"prompt": prompt}))
            task_id = str(run["task_id"])
            result = {
                "task_id": task_id,
                "recalled": recall,
                "run": run,
                "trace": self.repository.get_task_trace(task_id),
                "task_memory": build_task_memory_context(self.repository, task_id, limit=limit),
                "information_gaps": build_information_gap_analysis(self.repository, task_id),
                "search_queries": build_search_query_plan(self.repository, task_id, limit=limit),
                "next_step": build_next_step_plan(self.repository, task_id, limit=limit),
            }
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "structure_subject":
            prompt = str(arguments["prompt"])
            run = dict(self.call("task_evolve", {"prompt": prompt}))
            task_id = str(run["task_id"])
            result = {
                "task_id": task_id,
                "run": run,
                "schema": self.repository.get_task_schema(task_id),
                "trace": self.repository.get_task_trace(task_id),
                "information_gaps": build_information_gap_analysis(self.repository, task_id),
                "search_queries": build_search_query_plan(self.repository, task_id),
                "next_step": build_next_step_plan(self.repository, task_id),
            }
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "inspect_latest_changes":
            task_id = self._resolve_latest_task_id(
                task_id=_optional_string(arguments.get("task_id")),
                subject=_optional_string(arguments.get("subject")),
            )
            if task_id is None:
                result = {"found": False, "reason": "no_tasks"}
                logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
                return result
            task = self.repository.get_task(task_id)
            result = {
                "found": True,
                "task_id": task_id,
                **_family_review_summary(task),
                **_branch_decision_summary(task),
                "task": task,
                "trace": self.repository.get_task_trace(task_id),
                "schema": self.repository.get_task_schema(task_id),
                "events": self.repository.get_task_events(task_id),
                "task_memory": build_task_memory_context(self.repository, task_id, limit=6),
                "information_gaps": build_information_gap_analysis(self.repository, task_id),
                "search_queries": build_search_query_plan(self.repository, task_id, limit=6),
                "next_step": build_next_step_plan(self.repository, task_id, limit=6),
            }
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "analyze_information_gaps":
            subject = _optional_string(arguments.get("subject"))
            task_id = self._resolve_latest_task_id(
                task_id=_optional_string(arguments.get("task_id")),
                subject=subject,
            )
            if task_id is None:
                result = {"found": False, **build_subject_bootstrap_plan(subject or "subject")}
                logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
                return result
            result = {"found": True, **build_information_gap_analysis(self.repository, task_id)}
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "prepare_search_queries":
            subject = _optional_string(arguments.get("subject"))
            task_id = self._resolve_latest_task_id(
                task_id=_optional_string(arguments.get("task_id")),
                subject=subject,
            )
            limit = int(arguments.get("limit", 5))
            if task_id is None:
                result = {"found": False, **build_subject_bootstrap_plan(subject or "subject", limit=limit)}
                logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
                return result
            result = {"found": True, **build_search_query_plan(self.repository, task_id, limit=limit)}
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "plan_next_step":
            subject = _optional_string(arguments.get("subject"))
            task_id = self._resolve_latest_task_id(
                task_id=_optional_string(arguments.get("task_id")),
                subject=subject,
            )
            limit = int(arguments.get("limit", 5))
            if task_id is None:
                result = {"found": False, **build_subject_bootstrap_plan(subject or "subject", limit=limit)}
                logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
                return result
            result = {"found": True, **build_next_step_plan(self.repository, task_id, limit=limit)}
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "task_trace":
            result = self.repository.get_task_trace(str(arguments["task_id"]))
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "schema_status":
            result = self.repository.get_task_schema(str(arguments["task_id"]))
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "schema_apply":
            result = self._apply_schema(str(arguments["task_id"]))
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "artifact_read":
            result = self.repository.read_artifacts(
                str(arguments["task_id"]),
                str(arguments["artifact_type"]) if "artifact_type" in arguments else None,
            )
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "artifact_search":
            result = self.repository.search(str(arguments["query"]))
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "memory_search":
            result = build_memory_search(
                self.repository,
                str(arguments["query"]),
                limit=int(arguments.get("limit", 8)),
            )
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "memory_profile":
            result = build_workspace_profile_memory(
                self.repository,
                profile_id=str(arguments.get("profile_id", "workspace")),
            )
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "subject_memory":
            result = build_subject_memory(
                self.repository,
                str(arguments["subject"]),
                limit=int(arguments.get("limit", 6)),
            )
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
        if name == "task_memory_context":
            result = build_task_memory_context(
                self.repository,
                str(arguments["task_id"]),
                limit=int(arguments.get("limit", 6)),
            )
            logger.info("TraceRelay MCP tool end name=%s result=%s", name, _summarize_result(result))
            return result
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

    def _resolve_latest_task_id(self, *, task_id: str | None = None, subject: str | None = None) -> str | None:
        if task_id:
            return task_id
        if subject:
            normalized_subject = normalize_subject(subject)
            for task in self.repository.list_tasks():
                if normalize_subject(str(task.get("resolved_subject", ""))) == normalized_subject:
                    return str(task["task_id"])
            matches = self.repository.search(subject)
            if matches:
                return str(matches[0]["task_id"])
        tasks = self.repository.list_tasks()
        if not tasks:
            return None
        return str(tasks[0]["task_id"])

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
        name="continue_prior_work",
        description="Continue earlier work on the same subject, reuse prior memory, and run the next structured step.",
    )
    def continue_prior_work(prompt: str, subject: str | None = None, limit: int = 6) -> dict[str, object]:
        return dict(
            toolbox.call(
                "continue_prior_work",
                {
                    "prompt": prompt,
                    **({"subject": subject} if subject else {}),
                    "limit": limit,
                },
            )
        )

    @mcp.tool(
        name="structure_subject",
        description="Turn a natural-language research or analysis request into structured fields, schema evolution, and traceable output.",
    )
    def structure_subject(prompt: str) -> dict[str, object]:
        return dict(toolbox.call("structure_subject", {"prompt": prompt}))

    @mcp.tool(
        name="inspect_latest_changes",
        description="Inspect what changed in the latest run, including retries, family rechecks, and schema updates.",
    )
    def inspect_latest_changes(task_id: str | None = None, subject: str | None = None) -> dict[str, object]:
        return dict(
            toolbox.call(
                "inspect_latest_changes",
                {
                    **({"task_id": task_id} if task_id else {}),
                    **({"subject": subject} if subject else {}),
                },
            )
        )

    @mcp.tool(
        name="analyze_information_gaps",
        description="Explain which values, fields, or relations are still missing and what is already known.",
    )
    def analyze_information_gaps(task_id: str | None = None, subject: str | None = None) -> dict[str, object]:
        return dict(
            toolbox.call(
                "analyze_information_gaps",
                {
                    **({"task_id": task_id} if task_id else {}),
                    **({"subject": subject} if subject else {}),
                },
            )
        )

    @mcp.tool(
        name="prepare_search_queries",
        description="Generate narrow search queries based on the current gaps, known facts, and active schema.",
    )
    def prepare_search_queries(
        task_id: str | None = None,
        subject: str | None = None,
        limit: int = 5,
    ) -> dict[str, object]:
        return dict(
            toolbox.call(
                "prepare_search_queries",
                {
                    **({"task_id": task_id} if task_id else {}),
                    **({"subject": subject} if subject else {}),
                    "limit": limit,
                },
            )
        )

    @mcp.tool(
        name="plan_next_step",
        description="Recommend the next TraceRelay action, pre-search checks, and targeted queries before generic search.",
    )
    def plan_next_step(
        task_id: str | None = None,
        subject: str | None = None,
        limit: int = 5,
    ) -> dict[str, object]:
        return dict(
            toolbox.call(
                "plan_next_step",
                {
                    **({"task_id": task_id} if task_id else {}),
                    **({"subject": subject} if subject else {}),
                    "limit": limit,
                },
            )
        )

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


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _summarize_arguments(arguments: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for key, value in arguments.items():
        if key == "prompt":
            prompt = str(value).strip()
            summary[key] = prompt if len(prompt) <= 120 else f"{prompt[:117]}..."
            continue
        summary[key] = value
    return summary


def _summarize_result(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        summary: dict[str, object] = {}
        for key in (
            "task_id",
            "status",
            "reason",
            "found",
            "applied",
            "recommended_tool",
            "family_changed",
            "initial_family",
            "final_family",
            "chosen_branch_type",
            "completion_rate",
        ):
            if key in result:
                summary[key] = result[key]
        if "queries" in result and isinstance(result["queries"], list):
            summary["queries"] = len(result["queries"])
        if "recommended_queries" in result and isinstance(result["recommended_queries"], list):
            summary["recommended_queries"] = len(result["recommended_queries"])
        if "run" in result and isinstance(result["run"], dict):
            run = result["run"]
            summary["run"] = {
                "task_id": run.get("task_id"),
                "status": run.get("status"),
                "reason": run.get("reason"),
            }
        if "schema" in result and isinstance(result["schema"], dict):
            active_schema = result["schema"].get("active_schema")
            if isinstance(active_schema, dict):
                summary["schema"] = {
                    "schema_id": active_schema.get("schema_id"),
                    "version": active_schema.get("version"),
                }
        if "recalled" in result and isinstance(result["recalled"], dict):
            summary["recalled"] = {
                "kind": result["recalled"].get("kind"),
                "subject": result["recalled"].get("subject"),
            }
        if not summary:
            summary["keys"] = sorted(result.keys())
        return summary
    if isinstance(result, list):
        return {"count": len(result)}
    return {"type": type(result).__name__}


def _family_review_summary(task: dict[str, object]) -> dict[str, object]:
    interpretation = dict(task.get("interpretation") or {})
    final_family = str(interpretation.get("family") or "").strip()
    initial_family = str(interpretation.get("initial_family") or final_family).strip()
    family_review_rationale = str(
        interpretation.get("family_review_rationale") or interpretation.get("family_rationale") or ""
    ).strip()
    return {
        "family_changed": bool(initial_family and final_family and initial_family != final_family),
        "initial_family": initial_family,
        "final_family": final_family,
        "family_review_rationale": family_review_rationale,
    }


def _branch_decision_summary(task: dict[str, object]) -> dict[str, object]:
    branch_decision = dict(task.get("latest_branch_decision") or {})
    strategy_selection = dict(task.get("strategy_selection") or {})
    return {
        "chosen_branch_type": str(branch_decision.get("chosen_branch_type") or "").strip(),
        "selected_strategy": str(
            strategy_selection.get("chosen_branch_type") or branch_decision.get("chosen_branch_type") or ""
        ).strip(),
        "completion_rate": branch_decision.get("completion_rate"),
        "branch_rationale": str(branch_decision.get("rationale") or "").strip(),
        "strategy_rationale": str(
            strategy_selection.get("rationale") or branch_decision.get("rationale") or ""
        ).strip(),
        "telemetry": dict(branch_decision.get("telemetry") or {}),
    }
