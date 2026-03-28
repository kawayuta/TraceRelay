from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..web.repository import build_task_memory_records, build_user_profile_records
from ..task_flow import JsonlArtifactStore

try:
    from psycopg.types.json import Jsonb
except Exception:  # pragma: no cover
    Jsonb = None


@dataclass(frozen=True)
class ProjectionRow:
    table: str
    values: dict[str, Any]
    conflict_columns: tuple[str, ...] = ("artifact_id",)


class TaskRuntimeProjector:
    def __init__(self, store: JsonlArtifactStore) -> None:
        self.store = store

    def schema_sql(self) -> str:
        path = Path(__file__).resolve().parents[1] / "sql" / "003_task_runtime.sql"
        return path.read_text(encoding="utf-8")

    def apply_schema(self, connection: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute(self.schema_sql())
        connection.commit()

    def rows_for_task(self, task_id: str) -> tuple[ProjectionRow, ...]:
        artifacts = self.store.list_for_task(task_id)
        rows: list[ProjectionRow] = []
        for artifact_order, artifact in enumerate(artifacts, start=1):
            payload = dict(artifact.payload)
            rows.append(
                ProjectionRow(
                    table="task_artifact",
                    values={
                        "task_id": artifact.task_id,
                        "artifact_id": artifact.artifact_id,
                        "artifact_order": artifact_order,
                        "artifact_type": artifact.artifact_type,
                        "payload": payload,
                    },
                )
            )
            if artifact.artifact_type == "task_prompt":
                rows.append(
                    ProjectionRow(
                        table="task_prompt",
                        values={
                            "task_id": artifact.task_id,
                            "artifact_id": artifact.artifact_id,
                            "prompt": payload.get("prompt"),
                            "locale": payload.get("locale"),
                        },
                    )
                )
            elif artifact.artifact_type == "task_interpretation":
                rows.append(
                    ProjectionRow(
                        table="task_interpretation",
                        values={
                            "task_id": artifact.task_id,
                            "artifact_id": artifact.artifact_id,
                            "payload": payload,
                        },
                    )
                )
            elif artifact.artifact_type == "task_run":
                rows.append(
                    ProjectionRow(
                        table="task_run",
                        values={
                            "task_id": artifact.task_id,
                            "artifact_id": artifact.artifact_id,
                            "status": payload.get("status"),
                            "reason": payload.get("reason"),
                        },
                    )
                )
            elif artifact.artifact_type == "schema_version":
                rows.append(
                    ProjectionRow(
                        table="schema_version",
                        values={
                            "task_id": artifact.task_id,
                            "artifact_id": artifact.artifact_id,
                            "schema_id": payload.get("schema_id"),
                            "family": payload.get("family"),
                            "version": payload.get("version"),
                            "payload": payload,
                        },
                    )
                )
            elif artifact.artifact_type == "task_extraction":
                rows.append(
                    ProjectionRow(
                        table="task_extraction",
                        values={
                            "task_id": artifact.task_id,
                            "artifact_id": artifact.artifact_id,
                            "attempt": payload.get("attempt"),
                            "payload": payload.get("payload"),
                        },
                    )
                )
            elif artifact.artifact_type == "coverage_report":
                rows.append(
                    ProjectionRow(
                        table="coverage_report",
                        values={
                            "task_id": artifact.task_id,
                            "artifact_id": artifact.artifact_id,
                            "payload": payload,
                        },
                    )
                )
            elif artifact.artifact_type == "schema_candidate":
                rows.append(
                    ProjectionRow(
                        table="task_schema_candidate_map",
                        values={
                            "task_id": artifact.task_id,
                            "artifact_id": artifact.artifact_id,
                            "candidate_id": payload.get("candidate_id"),
                            "requirement_id": payload.get("requirement_id"),
                            "payload": payload,
                        },
                    )
                )
        memory_artifacts = [
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "payload": artifact.payload,
            }
            for artifact in artifacts
        ]
        for record in build_task_memory_records(task_id, memory_artifacts):
            rows.append(
                ProjectionRow(
                    table=str(record.get("table", record["record_type"])),
                    values=_projection_values(record),
                    conflict_columns=tuple(str(column) for column in record.get("conflict_columns", ("artifact_id",))),
                )
            )
        return tuple(rows)

    def build_reindex_plan(self) -> tuple[ProjectionRow, ...]:
        rows: list[ProjectionRow] = []
        for task_id in self.store.list_task_ids():
            rows.extend(self.rows_for_task(task_id))
        all_artifacts = [
            {
                "artifact_id": artifact.artifact_id,
                "task_id": artifact.task_id,
                "artifact_type": artifact.artifact_type,
                "payload": artifact.payload,
            }
            for artifact in self.store.all_artifacts()
        ]
        for record in build_user_profile_records(all_artifacts):
            rows.append(
                ProjectionRow(
                    table=str(record.get("table", record["record_type"])),
                    values=_projection_values(record),
                    conflict_columns=tuple(str(column) for column in record.get("conflict_columns", ("artifact_id",))),
                )
            )
        return tuple(rows)

    def reindex(self, connection: Any) -> None:
        for row in self.build_reindex_plan():
            self._upsert_row(connection, row)

    def sync_task(self, connection: Any, task_id: str) -> None:
        for row in self.rows_for_task(task_id):
            self._upsert_row(connection, row)
        all_artifacts = [
            {
                "artifact_id": artifact.artifact_id,
                "task_id": artifact.task_id,
                "artifact_type": artifact.artifact_type,
                "payload": artifact.payload,
            }
            for artifact in self.store.all_artifacts()
        ]
        for record in build_user_profile_records(all_artifacts):
            row = ProjectionRow(
                table=str(record.get("table", record["record_type"])),
                values=_projection_values(record),
                conflict_columns=tuple(str(column) for column in record.get("conflict_columns", ("artifact_id",))),
            )
            self._upsert_row(connection, row)

    def _upsert_row(self, connection: Any, row: ProjectionRow) -> None:
        columns = list(row.values.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        assignments = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in columns if column not in row.conflict_columns
        )
        if not assignments:
            assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns)
        sql = (
            f"INSERT INTO {row.table} ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(row.conflict_columns)}) DO UPDATE SET {assignments}"
        )
        values = [self._adapt(row.values[column]) for column in columns]
        with connection.cursor() as cursor:
            cursor.execute(sql, values)
        connection.commit()

    def dump_plan_json(self) -> str:
        plan = [{"table": row.table, "values": row.values} for row in self.build_reindex_plan()]
        return json.dumps(plan, ensure_ascii=False, indent=2)

    def _adapt(self, value: Any) -> Any:
        if isinstance(value, dict) and Jsonb is not None:
            return Jsonb(value)
        return value


def _projection_values(record: dict[str, Any]) -> dict[str, Any]:
    if str(record.get("record_type", "")) == "user_profile":
        return {
            "profile_key": record.get("profile_key"),
            "artifact_id": record.get("artifact_id"),
            "summary": record.get("summary"),
            "payload": record.get("payload"),
            "embedding": record.get("embedding"),
        }
    return {
        key: value
        for key, value in record.items()
        if key not in {"table", "record_type", "conflict_columns"}
    }
