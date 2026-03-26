from __future__ import annotations

from typing import Any, Callable, Protocol

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

from ..config import postgres_dsn_from_env
from ..task_flow import JsonlArtifactStore
from .trace import build_task_trace


class TaskBrowseRepository(Protocol):
    def list_tasks(self) -> list[dict[str, object]]:
        ...

    def get_task(self, task_id: str) -> dict[str, object]:
        ...

    def get_task_coverage(self, task_id: str) -> dict[str, object]:
        ...

    def get_task_schema(self, task_id: str) -> dict[str, object]:
        ...

    def get_task_events(self, task_id: str) -> list[dict[str, object]]:
        ...

    def get_task_trace(self, task_id: str) -> dict[str, object]:
        ...

    def read_artifacts(self, task_id: str, artifact_type: str | None = None) -> list[dict[str, object]]:
        ...

    def search(self, query: str) -> list[dict[str, object]]:
        ...


class TaskRepository:
    def __init__(self, store: JsonlArtifactStore) -> None:
        self.store = store

    def list_tasks(self) -> list[dict[str, object]]:
        tasks: list[dict[str, object]] = []
        for task_id in self.store.list_task_ids():
            summary = self.get_task(task_id)
            tasks.append(
                {
                    "task_id": task_id,
                    "prompt": summary["prompt"],
                    "resolved_subject": summary["interpretation"].get("resolved_subject"),
                    "family": summary["interpretation"].get("family"),
                    "status": summary["run"].get("status"),
                    "reason": summary["run"].get("reason"),
                }
            )
        return tasks

    def get_task(self, task_id: str) -> dict[str, object]:
        return _assemble_task(
            task_id,
            [
                {
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type,
                    "payload": artifact.payload,
                }
                for artifact in self.store.list_for_task(task_id)
            ],
        )

    def get_task_coverage(self, task_id: str) -> dict[str, object]:
        task = self.get_task(task_id)
        reports = task["coverage_reports"]
        return reports[-1] if reports else {}

    def get_task_schema(self, task_id: str) -> dict[str, object]:
        task = self.get_task(task_id)
        return {
            "versions": task["schema_versions"],
            "active_schema": task["schema_versions"][-1] if task["schema_versions"] else None,
            "gap": task["schema_gap"],
            "requirement": task["schema_requirement"],
            "candidate": task["schema_candidate"],
            "review": task["schema_review"],
        }

    def get_task_events(self, task_id: str) -> list[dict[str, object]]:
        task = self.get_task(task_id)
        return list(task["events"])

    def get_task_trace(self, task_id: str) -> dict[str, object]:
        task = self.get_task(task_id)
        artifacts = self.read_artifacts(task_id)
        return build_task_trace(task, artifacts)

    def read_artifacts(self, task_id: str, artifact_type: str | None = None) -> list[dict[str, object]]:
        artifacts = self.store.list_for_task(task_id)
        result = []
        for artifact in artifacts:
            if artifact_type is None or artifact.artifact_type == artifact_type:
                result.append(
                    {
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "payload": artifact.payload,
                    }
                )
        return result

    def search(self, query: str) -> list[dict[str, object]]:
        lowered = query.lower()
        matches: list[dict[str, object]] = []
        for task in self.list_tasks():
            haystacks = [
                str(task.get("prompt", "")),
                str(task.get("resolved_subject", "")),
                str(task.get("family", "")),
            ]
            if any(lowered in haystack.lower() for haystack in haystacks):
                matches.append(task)
        return matches


class PostgresTaskRepository:
    def __init__(
        self,
        dsn: str | None = None,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        if connection_factory is None:
            if psycopg is None:  # pragma: no cover
                raise RuntimeError("psycopg is required for PostgresTaskRepository")
        self.dsn = postgres_dsn_from_env() if dsn is None else dsn
        self.connection_factory = connection_factory

    def list_tasks(self) -> list[dict[str, object]]:
        sql = """
            SELECT DISTINCT ON (p.task_id)
                p.task_id,
                p.prompt,
                COALESCE(i.payload->>'resolved_subject', '') AS resolved_subject,
                COALESCE(i.payload->>'family', '') AS family,
                COALESCE(r.status, '') AS status,
                COALESCE(r.reason, '') AS reason
            FROM task_prompt AS p
            LEFT JOIN task_interpretation AS i ON i.task_id = p.task_id
            LEFT JOIN task_run AS r ON r.task_id = p.task_id
            ORDER BY p.task_id, r.artifact_id DESC NULLS LAST, i.artifact_id DESC NULLS LAST, p.artifact_id DESC
        """
        rows = self._fetchall(sql)
        return [
            {
                "task_id": row[0],
                "prompt": row[1],
                "resolved_subject": row[2],
                "family": row[3],
                "status": row[4],
                "reason": row[5],
            }
            for row in rows
        ]

    def get_task(self, task_id: str) -> dict[str, object]:
        artifacts = self.read_artifacts(task_id)
        return _assemble_task(task_id, artifacts)

    def get_task_coverage(self, task_id: str) -> dict[str, object]:
        task = self.get_task(task_id)
        reports = task["coverage_reports"]
        return reports[-1] if reports else {}

    def get_task_schema(self, task_id: str) -> dict[str, object]:
        task = self.get_task(task_id)
        return {
            "versions": task["schema_versions"],
            "active_schema": task["schema_versions"][-1] if task["schema_versions"] else None,
            "gap": task["schema_gap"],
            "requirement": task["schema_requirement"],
            "candidate": task["schema_candidate"],
            "review": task["schema_review"],
        }

    def get_task_events(self, task_id: str) -> list[dict[str, object]]:
        task = self.get_task(task_id)
        return list(task["events"])

    def get_task_trace(self, task_id: str) -> dict[str, object]:
        task = self.get_task(task_id)
        artifacts = self.read_artifacts(task_id)
        return build_task_trace(task, artifacts)

    def read_artifacts(self, task_id: str, artifact_type: str | None = None) -> list[dict[str, object]]:
        sql = """
            SELECT artifact_id, artifact_type, payload
            FROM task_artifact
            WHERE task_id = %s
        """
        params: list[object] = [task_id]
        if artifact_type is not None:
            sql += " AND artifact_type = %s"
            params.append(artifact_type)
        sql += " ORDER BY artifact_order"
        rows = self._fetchall(sql, tuple(params))
        if not rows and artifact_type is None:
            raise KeyError(task_id)
        return [
            {
                "artifact_id": row[0],
                "artifact_type": row[1],
                "payload": dict(row[2]),
            }
            for row in rows
        ]

    def search(self, query: str) -> list[dict[str, object]]:
        pattern = f"%{query}%"
        sql = """
            SELECT DISTINCT ON (p.task_id)
                p.task_id,
                p.prompt,
                COALESCE(i.payload->>'resolved_subject', '') AS resolved_subject,
                COALESCE(i.payload->>'family', '') AS family,
                COALESCE(r.status, '') AS status,
                COALESCE(r.reason, '') AS reason
            FROM task_prompt AS p
            LEFT JOIN task_interpretation AS i ON i.task_id = p.task_id
            LEFT JOIN task_run AS r ON r.task_id = p.task_id
            WHERE
                p.prompt ILIKE %s
                OR COALESCE(i.payload->>'resolved_subject', '') ILIKE %s
                OR COALESCE(i.payload->>'family', '') ILIKE %s
            ORDER BY p.task_id, r.artifact_id DESC NULLS LAST, i.artifact_id DESC NULLS LAST, p.artifact_id DESC
        """
        rows = self._fetchall(sql, (pattern, pattern, pattern))
        return [
            {
                "task_id": row[0],
                "prompt": row[1],
                "resolved_subject": row[2],
                "family": row[3],
                "status": row[4],
                "reason": row[5],
            }
            for row in rows
        ]

    def _connect(self) -> Any:
        if self.connection_factory is not None:
            return self.connection_factory()
        assert psycopg is not None  # pragma: no cover
        assert self.dsn is not None
        return psycopg.connect(self.dsn)

    def _fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())


def _assemble_task(task_id: str, artifacts: list[dict[str, object]]) -> dict[str, object]:
    if not artifacts:
        raise KeyError(task_id)
    latest_by_type: dict[str, dict[str, object]] = {}
    extractions: list[dict[str, object]] = []
    coverages: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    schema_versions: list[dict[str, object]] = []
    for artifact in artifacts:
        artifact_type = str(artifact["artifact_type"])
        payload = dict(artifact["payload"])
        latest_by_type[artifact_type] = payload
        if artifact_type == "task_extraction":
            extractions.append(payload)
        elif artifact_type == "coverage_report":
            coverages.append(payload)
        elif artifact_type == "task_event":
            events.append(payload)
        elif artifact_type in {"schema_version", "schema_reference"}:
            schema_versions.append(payload)
    return {
        "task_id": task_id,
        "prompt": latest_by_type.get("task_prompt", {}).get("prompt"),
        "interpretation": latest_by_type.get("task_interpretation", {}),
        "extractions": extractions,
        "coverage_reports": coverages,
        "run": latest_by_type.get("task_run", {}),
        "schema_versions": schema_versions,
        "schema_gap": latest_by_type.get("schema_gap"),
        "schema_requirement": latest_by_type.get("schema_requirement"),
        "schema_candidate": latest_by_type.get("schema_candidate"),
        "schema_review": latest_by_type.get("schema_review"),
        "events": events,
    }
