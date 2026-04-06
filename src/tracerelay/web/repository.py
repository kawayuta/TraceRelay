from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Protocol

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

from ..config import postgres_dsn_from_env
from ..embeddings import cosine_similarity, embed_text, embedding_record, embedder_from_env
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

    def list_memory_documents(
        self,
        *,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        ...

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        ...

    def get_task_memory_context(self, task_id: str) -> dict[str, object]:
        ...

    def list_user_profiles(self) -> list[dict[str, object]]:
        ...

    def get_user_profile(self, profile_key: str = "default") -> dict[str, object]:
        ...

    def get_subject_memory(self, subject_key: str, family: str | None = None) -> dict[str, object]:
        ...


class TaskRepository:
    def __init__(self, store: JsonlArtifactStore) -> None:
        self.store = store

    def list_tasks(self) -> list[dict[str, object]]:
        tasks: list[dict[str, object]] = []
        artifacts = [
            {
                "artifact_id": artifact.artifact_id,
                "task_id": artifact.task_id,
                "artifact_type": artifact.artifact_type,
                "payload": artifact.payload,
                "recorded_at": artifact.recorded_at,
            }
            for artifact in self.store.all_artifacts()
        ]
        grouped = _group_artifacts_by_task(artifacts)
        for task_id, task_artifacts in grouped.items():
            summary = _assemble_task(task_id, task_artifacts)
            tasks.append(
                {
                    "task_id": task_id,
                    "prompt": summary["prompt"],
                    "resolved_subject": summary["interpretation"].get("resolved_subject"),
                    "family": summary["interpretation"].get("family"),
                    "status": summary["run"].get("status"),
                    "reason": summary["run"].get("reason"),
                    "latest_processed_at": _latest_recorded_at(task_artifacts),
                }
            )
        tasks.sort(
            key=lambda item: (
                str(item.get("latest_processed_at", "")),
                str(item.get("task_id", "")),
            ),
            reverse=True,
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

    def list_memory_documents(
        self,
        *,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        normalized_subject = _normalize_subject_key(subject_key) if subject_key is not None else None
        for task_id in self.store.list_task_ids():
            task_records = build_task_memory_records(task_id, self._task_artifacts(task_id))
            for record in task_records:
                if record["record_type"] == "user_profile":
                    continue
                if profile_key is not None and record.get("profile_key") != profile_key:
                    continue
                if subject_key is not None and not _memory_record_matches_subject(record, normalized_subject or ""):
                    continue
                if memory_type is not None and record.get("memory_type") != memory_type:
                    continue
                records.append(_decode_memory_record(record))
        return records

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        normalized_subject = _normalize_subject_key(subject_key) if subject_key is not None else None
        records = self.list_memory_documents(
            profile_key=profile_key,
            subject_key=normalized_subject,
            memory_type=memory_type,
        )
        return _rank_memory_records(query, records, limit=limit, memory_type=memory_type)

    def get_task_memory_context(self, task_id: str) -> dict[str, object]:
        for record in build_task_memory_records(task_id, self._task_artifacts(task_id)):
            if record["record_type"] == "task_memory_context":
                return _decode_memory_record(record)
        raise KeyError(task_id)

    def list_user_profiles(self) -> list[dict[str, object]]:
        profiles: dict[str, dict[str, object]] = {}
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
            profiles[str(record["profile_key"])] = _decode_memory_record(record)
        return [profiles[key] for key in sorted(profiles)]

    def get_user_profile(self, profile_key: str = "default") -> dict[str, object]:
        for profile in self.list_user_profiles():
            if profile.get("profile_key") == profile_key:
                return profile
        raise KeyError(profile_key)

    def get_subject_memory(self, subject_key: str, family: str | None = None) -> dict[str, object]:
        normalized_subject = _normalize_subject_key(subject_key)
        matching_documents: list[dict[str, object]] = []
        matching_contexts: list[dict[str, object]] = []
        matching_profile_keys: set[str] = set()
        for task_id in self.store.list_task_ids():
            for record in build_task_memory_records(task_id, self._task_artifacts(task_id)):
                decoded = _decode_memory_record(record)
                if family is not None and decoded.get("family") not in {family, None, ""}:
                    continue
                if not _memory_record_matches_subject(decoded, normalized_subject):
                    continue
                matching_profile_keys.add(str(decoded.get("profile_key", "default")))
                if decoded["record_type"] == "task_memory_context":
                    matching_contexts.append(decoded)
                else:
                    matching_documents.append(decoded)
        profiles = [profile for profile in self.list_user_profiles() if profile.get("profile_key") in matching_profile_keys]
        return {
            "subject_key": normalized_subject,
            "family": family,
            "memory_documents": matching_documents,
            "task_memory_contexts": matching_contexts,
            "profiles": profiles,
        }

    def _task_artifacts(self, task_id: str) -> list[dict[str, object]]:
        return [
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "payload": artifact.payload,
            }
            for artifact in self.store.list_for_task(task_id)
        ]


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
            WITH task_latest AS (
                SELECT
                    task_id,
                    MAX(recorded_at) AS latest_processed_at
                FROM task_artifact
                GROUP BY task_id
            )
            SELECT *
            FROM (
                SELECT DISTINCT ON (p.task_id)
                    p.task_id,
                    p.prompt,
                    COALESCE(i.payload->>'resolved_subject', '') AS resolved_subject,
                    COALESCE(i.payload->>'family', '') AS family,
                    COALESCE(r.status, '') AS status,
                    COALESCE(r.reason, '') AS reason,
                    l.latest_processed_at
                FROM task_prompt AS p
                LEFT JOIN task_interpretation AS i ON i.task_id = p.task_id
                LEFT JOIN task_run AS r ON r.task_id = p.task_id
                LEFT JOIN task_latest AS l ON l.task_id = p.task_id
                ORDER BY p.task_id, r.artifact_id DESC NULLS LAST, i.artifact_id DESC NULLS LAST, p.artifact_id DESC
            ) AS task_summary
            ORDER BY latest_processed_at DESC NULLS LAST, task_id DESC
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
                "latest_processed_at": "" if row[6] is None else str(row[6]),
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
            WITH task_latest AS (
                SELECT
                    task_id,
                    MAX(recorded_at) AS latest_processed_at
                FROM task_artifact
                GROUP BY task_id
            )
            SELECT *
            FROM (
                SELECT DISTINCT ON (p.task_id)
                    p.task_id,
                    p.prompt,
                    COALESCE(i.payload->>'resolved_subject', '') AS resolved_subject,
                    COALESCE(i.payload->>'family', '') AS family,
                    COALESCE(r.status, '') AS status,
                    COALESCE(r.reason, '') AS reason,
                    l.latest_processed_at
                FROM task_prompt AS p
                LEFT JOIN task_interpretation AS i ON i.task_id = p.task_id
                LEFT JOIN task_run AS r ON r.task_id = p.task_id
                LEFT JOIN task_latest AS l ON l.task_id = p.task_id
                WHERE
                    p.prompt ILIKE %s
                    OR COALESCE(i.payload->>'resolved_subject', '') ILIKE %s
                    OR COALESCE(i.payload->>'family', '') ILIKE %s
                ORDER BY p.task_id, r.artifact_id DESC NULLS LAST, i.artifact_id DESC NULLS LAST, p.artifact_id DESC
            ) AS task_summary
            ORDER BY latest_processed_at DESC NULLS LAST, task_id DESC
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
                "latest_processed_at": "" if row[6] is None else str(row[6]),
            }
            for row in rows
        ]

    def list_memory_documents(
        self,
        *,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        rows.extend(
            self._fetch_memory_rows(
                "memory_document",
                profile_key=profile_key,
                subject_key=subject_key,
                memory_type=memory_type,
            )
        )
        rows.extend(
            self._fetch_memory_rows(
                "task_memory_context",
                profile_key=profile_key,
                subject_key=subject_key,
                memory_type=memory_type,
            )
        )
        rows.sort(key=lambda item: (str(item.get("task_id", "")), str(item.get("memory_type", "")), str(item.get("artifact_id", ""))))
        return rows

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        normalized_subject = _normalize_subject_key(subject_key) if subject_key is not None else None
        records = self.list_memory_documents(
            profile_key=profile_key,
            subject_key=normalized_subject,
            memory_type=memory_type,
        )
        return _rank_memory_records(query, records, limit=limit, memory_type=memory_type)

    def get_task_memory_context(self, task_id: str) -> dict[str, object]:
        sql = """
            SELECT artifact_id, task_id, memory_type, profile_key, subject_key, family, summary, payload, embedding
            FROM task_memory_context
            WHERE task_id = %s
            ORDER BY artifact_id DESC
            LIMIT 1
        """
        rows = self._fetchall(sql, (task_id,))
        if not rows:
            raise KeyError(task_id)
        return _decode_memory_row(rows[0], "task_memory_context")

    def list_user_profiles(self) -> list[dict[str, object]]:
        sql = """
            SELECT profile_key, artifact_id, summary, payload, embedding
            FROM user_profile
            ORDER BY profile_key
        """
        rows = self._fetchall(sql)
        return [_decode_user_profile_row(row) for row in rows]

    def get_user_profile(self, profile_key: str = "default") -> dict[str, object]:
        sql = """
            SELECT profile_key, artifact_id, summary, payload, embedding
            FROM user_profile
            WHERE profile_key = %s
            LIMIT 1
        """
        rows = self._fetchall(sql, (profile_key,))
        if not rows:
            raise KeyError(profile_key)
        return _decode_user_profile_row(rows[0])

    def get_subject_memory(self, subject_key: str, family: str | None = None) -> dict[str, object]:
        normalized_subject = _normalize_subject_key(subject_key)
        records = self.list_memory_documents(subject_key=normalized_subject)
        documents = [record for record in records if record.get("record_type") == "memory_document"]
        contexts = [record for record in records if record.get("record_type") == "task_memory_context"]
        if family is not None:
            documents = [record for record in documents if record.get("family") in {family, None, ""}]
            contexts = [record for record in contexts if record.get("family") in {family, None, ""}]
        profile_keys = sorted({str(record.get("profile_key", "default")) for record in documents + contexts})
        profiles = [profile for profile in self.list_user_profiles() if profile.get("profile_key") in profile_keys]
        return {
            "subject_key": normalized_subject,
            "family": family,
            "memory_documents": documents,
            "task_memory_contexts": contexts,
            "profiles": profiles,
        }

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

    def _fetch_memory_rows(
        self,
        table: str,
        *,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        sql = f"""
            SELECT artifact_id, task_id, memory_type, profile_key, subject_key, family, summary, payload, embedding
            FROM {table}
        """
        clauses: list[str] = []
        params: list[object] = []
        if profile_key is not None:
            clauses.append("profile_key = %s")
            params.append(profile_key)
        if subject_key is not None:
            clauses.append("subject_key = %s")
            params.append(_normalize_subject_key(subject_key))
        if memory_type is not None and table == "memory_document":
            clauses.append("memory_type = %s")
            params.append(memory_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY task_id, artifact_id"
        rows = self._fetchall(sql, tuple(params))
        decoded = [_decode_memory_row(row, table) for row in rows]
        if memory_type is not None and table == "task_memory_context":
            decoded = [record for record in decoded if record.get("memory_type") == memory_type]
        return decoded

def _assemble_task(task_id: str, artifacts: list[dict[str, object]]) -> dict[str, object]:
    if not artifacts:
        raise KeyError(task_id)
    latest_by_type: dict[str, dict[str, object]] = {}
    extractions: list[dict[str, object]] = []
    coverages: list[dict[str, object]] = []
    branch_decisions: list[dict[str, object]] = []
    family_probes: list[dict[str, object]] = []
    strategy_probes: list[dict[str, object]] = []
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
        elif artifact_type == "task_family_probe":
            family_probes.append(payload)
        elif artifact_type == "task_strategy_probe":
            strategy_probes.append(payload)
        elif artifact_type == "task_branch_decision":
            branch_decisions.append(payload)
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
        "evidence_bundle": latest_by_type.get("task_evidence_bundle"),
        "family_probes": family_probes,
        "family_selection": latest_by_type.get("task_family_selection"),
        "strategy_probes": strategy_probes,
        "strategy_selection": latest_by_type.get("task_strategy_selection"),
        "branch_decisions": branch_decisions,
        "latest_branch_decision": branch_decisions[-1] if branch_decisions else None,
        "run": latest_by_type.get("task_run", {}),
        "schema_versions": schema_versions,
        "schema_gap": latest_by_type.get("schema_gap"),
        "schema_requirement": latest_by_type.get("schema_requirement"),
        "schema_candidate": latest_by_type.get("schema_candidate"),
        "schema_review": latest_by_type.get("schema_review"),
        "events": events,
    }


def build_task_memory_records(task_id: str, artifacts: list[dict[str, object]]) -> tuple[dict[str, object], ...]:
    task = _assemble_task(task_id, artifacts)
    latest_by_type = _latest_by_type(artifacts)
    prompt_payload = dict(latest_by_type.get("task_prompt", {}))
    interpretation = dict(task.get("interpretation", {}))
    run = dict(task.get("run", {}))
    extractions = list(task.get("extractions", []))
    coverage_reports = list(task.get("coverage_reports", []))
    profile_key = _profile_key_for_task(prompt_payload, interpretation)
    subject_key = _subject_key_for_task(task)
    subject_aliases = _subject_aliases_for_task(task)
    family = str(interpretation.get("family") or run.get("family") or "")
    resolved_subject = str(interpretation.get("resolved_subject", ""))
    latest_extraction = dict(extractions[-1]) if extractions else {}
    latest_coverage = dict(coverage_reports[-1]) if coverage_reports else {}
    schema_versions = list(task.get("schema_versions", []))
    active_schema = dict(schema_versions[-1]) if schema_versions else {}

    task_summary_summary = (
        f"{resolved_subject or task_id} as {family or 'n/a'}: "
        f"{run.get('status', 'unknown')} / {run.get('reason', 'unknown')}"
    )
    subject_summary = _subject_summary_text(
        resolved_subject=resolved_subject,
        family=family,
        latest_extraction=latest_extraction,
        coverage=latest_coverage,
    )
    task_context_summary = (
        f"Context for {resolved_subject or task_id}: "
        f"{len(extractions)} extraction(s), "
        f"{len(schema_versions)} schema version(s), "
        f"status {run.get('status', 'unknown')}"
    )

    records: list[dict[str, object]] = [
        _memory_record(
            record_type="memory_document",
            memory_type="task_summary",
            artifact_id=_stable_memory_id("memory", task_id, "task_summary"),
            task_id=task_id,
            profile_key=profile_key,
            subject_key=subject_key,
            family=family,
            summary=task_summary_summary,
            payload={
                "task_id": task_id,
                "profile_key": profile_key,
                "subject_key": subject_key,
                "subject_aliases": subject_aliases,
                "family": family,
                "resolved_subject": resolved_subject,
                "prompt": task.get("prompt"),
                "status": run.get("status"),
                "reason": run.get("reason"),
                "schema_version": active_schema.get("version"),
                "schema_id": active_schema.get("schema_id"),
                "coverage": latest_coverage,
                "latest_extraction": latest_extraction,
            },
        ),
        _memory_record(
            record_type="memory_document",
            memory_type="subject_memory",
            artifact_id=_stable_memory_id("memory", task_id, "subject_memory", subject_key),
            task_id=task_id,
            profile_key=profile_key,
            subject_key=subject_key,
            family=family,
            summary=subject_summary,
            payload={
                "task_id": task_id,
                "profile_key": profile_key,
                "subject_key": subject_key,
                "subject_aliases": subject_aliases,
                "family": family,
                "resolved_subject": resolved_subject,
                "facts": _fact_lines_from_extraction(latest_extraction),
                "coverage": latest_coverage,
                "schema_version": active_schema.get("version"),
                "schema_id": active_schema.get("schema_id"),
            },
        ),
        _memory_record(
            record_type="task_memory_context",
            memory_type="task_memory_context",
            artifact_id=_stable_memory_id("memory", task_id, "context"),
            task_id=task_id,
            profile_key=profile_key,
            subject_key=subject_key,
            family=family,
            summary=task_context_summary,
            payload={
                "task_id": task_id,
                "profile_key": profile_key,
                "subject_key": subject_key,
                "subject_aliases": subject_aliases,
                "family": family,
                "resolved_subject": resolved_subject,
                "prompt": task.get("prompt"),
                "intent": interpretation.get("intent"),
                "task_shape": interpretation.get("task_shape"),
                "status": run.get("status"),
                "reason": run.get("reason"),
                "schema_version": active_schema.get("version"),
                "schema_id": active_schema.get("schema_id"),
                "schema_rationale": active_schema.get("rationale"),
                "coverage": latest_coverage,
                "extractions": extractions,
                "schema_versions": schema_versions,
                "events": list(task.get("events", [])),
            },
        ),
    ]

    for extraction in extractions:
        attempt = int(extraction.get("attempt", len(records)))
        records.append(
            _memory_record(
                record_type="memory_document",
                memory_type="extraction_snapshot",
                artifact_id=_stable_memory_id("memory", task_id, "extraction", str(attempt)),
                task_id=task_id,
                profile_key=profile_key,
                subject_key=subject_key,
                family=family,
                summary=_extraction_summary_text(task_id, extraction, subject_key, family),
                payload={
                    "task_id": task_id,
                    "profile_key": profile_key,
                    "subject_key": subject_key,
                    "subject_aliases": subject_aliases,
                    "family": family,
                    "attempt": attempt,
                    "status": extraction.get("status"),
                    "payload": extraction.get("payload", {}),
                    "provider_metadata": extraction.get("provider_metadata", {}),
                },
            )
        )

    return tuple(records)


def build_user_profile_records(artifacts: list[dict[str, object]]) -> tuple[dict[str, object], ...]:
    tasks = _group_artifacts_by_task(artifacts)
    snapshots = [_profile_snapshot(task_id, task_artifacts) for task_id, task_artifacts in tasks.items()]
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[str(snapshot["profile_key"])].append(snapshot)
    records: list[dict[str, object]] = []
    for profile_key in sorted(grouped):
        profile_snapshots = grouped[profile_key]
        profile = _build_profile_record(profile_key, profile_snapshots)
        records.append(profile)
    return tuple(records)


def _build_profile_record(profile_key: str, snapshots: list[dict[str, object]]) -> dict[str, object]:
    snapshots = sorted(
        snapshots,
        key=lambda item: (
            str(item.get("task_id", "")),
            str(item.get("subject_key", "")),
        ),
    )
    task_ids = [str(snapshot["task_id"]) for snapshot in snapshots]
    family_counts = Counter(str(snapshot.get("family", "")) for snapshot in snapshots if snapshot.get("family"))
    locale_counts = Counter(str(snapshot.get("locale", "")) for snapshot in snapshots if snapshot.get("locale"))
    subject_counts = Counter(str(snapshot.get("resolved_subject", "")) for snapshot in snapshots if snapshot.get("resolved_subject"))
    request_counts = Counter(str(item) for snapshot in snapshots for item in snapshot.get("requested_fields", []))
    relation_counts = Counter(str(item) for snapshot in snapshots for item in snapshot.get("requested_relations", []))
    preferred_locale = locale_counts.most_common(1)[0][0] if locale_counts else "auto"
    top_subjects = [item for item, _ in subject_counts.most_common(5)]
    top_families = [item for item, _ in family_counts.most_common(5)]
    top_fields = [item for item, _ in request_counts.most_common(10)]
    top_relations = [item for item, _ in relation_counts.most_common(10)]
    summary = (
        f"Profile {profile_key}: {len(task_ids)} task(s), "
        f"families {', '.join(top_families) if top_families else 'n/a'}, "
        f"subjects {', '.join(top_subjects) if top_subjects else 'n/a'}"
    )
    payload = {
        "profile_key": profile_key,
        "task_count": len(task_ids),
        "task_ids": task_ids,
        "family_counts": dict(family_counts),
        "locale_counts": dict(locale_counts),
        "subject_counts": dict(subject_counts),
        "preferred_locale": preferred_locale,
        "top_subjects": top_subjects,
        "top_families": top_families,
        "top_requested_fields": top_fields,
        "top_requested_relations": top_relations,
        "summary": summary,
    }
    return _memory_record(
        record_type="user_profile",
        memory_type="user_profile",
        artifact_id=_stable_memory_id("profile", profile_key),
        task_id="",
        profile_key=profile_key,
        subject_key=top_subjects[0] if top_subjects else profile_key,
        family=top_families[0] if top_families else "",
        summary=summary,
        payload=payload,
    )


def _profile_snapshot(task_id: str, artifacts: list[dict[str, object]]) -> dict[str, object]:
    task = _assemble_task(task_id, artifacts)
    latest_by_type = _latest_by_type(artifacts)
    prompt_payload = dict(latest_by_type.get("task_prompt", {}))
    interpretation = dict(task.get("interpretation", {}))
    profile_key = _profile_key_for_task(prompt_payload, interpretation)
    return {
        "task_id": task_id,
        "profile_key": profile_key,
        "subject_key": _subject_key_for_task(task),
        "resolved_subject": interpretation.get("resolved_subject", ""),
        "family": interpretation.get("family") or dict(task.get("run", {})).get("family", ""),
        "locale": prompt_payload.get("locale") or interpretation.get("locale", ""),
        "requested_fields": list(interpretation.get("requested_fields", [])),
        "requested_relations": list(interpretation.get("requested_relations", [])),
    }


def _group_artifacts_by_task(artifacts: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for artifact in artifacts:
        grouped[str(artifact["task_id"])].append(artifact)
    return grouped


def _latest_recorded_at(artifacts: list[dict[str, object]]) -> str:
    timestamps = [str(artifact.get("recorded_at", "") or "") for artifact in artifacts]
    return max(timestamps, default="")


def _latest_by_type(artifacts: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for artifact in artifacts:
        latest[str(artifact["artifact_type"])] = dict(artifact["payload"])
    return latest


def _profile_key_for_task(prompt_payload: dict[str, object], interpretation: dict[str, object]) -> str:
    user_id = str(prompt_payload.get("user_id") or "").strip()
    if user_id:
        return _normalize_subject_key(user_id)
    caller = str(prompt_payload.get("caller") or "").strip()
    if caller and caller != "user":
        return _normalize_subject_key(caller)
    if interpretation.get("locale"):
        return "default"
    return "default"


def _subject_key_for_task(task: dict[str, object]) -> str:
    interpretation = dict(task.get("interpretation", {}))
    resolved_subject = str(interpretation.get("resolved_subject") or task.get("prompt") or task.get("task_id") or "unknown")
    return _normalize_subject_key(resolved_subject)


def _subject_aliases_for_task(task: dict[str, object]) -> list[str]:
    interpretation = dict(task.get("interpretation", {}))
    resolved_subject = str(interpretation.get("resolved_subject") or task.get("prompt") or "")
    aliases: set[str] = set()
    normalized = _normalize_subject_key(resolved_subject)
    if normalized:
        aliases.add(normalized)
    aliases.update(_split_subject_aliases(resolved_subject))
    return sorted(alias for alias in aliases if alias)


def _split_subject_aliases(text: str) -> set[str]:
    aliases: set[str] = set()
    normalized = _normalize_subject_key(text)
    if normalized:
        aliases.add(normalized)
    for part in re.split(r"[\s/,&+|、・と\-]+", text):
        normalized_part = _normalize_subject_key(part)
        if normalized_part:
            aliases.add(normalized_part)
    tokens = [token for token in re.findall(r"[\w]+", text, flags=re.UNICODE) if token]
    if len(tokens) >= 2:
        aliases.add(_normalize_subject_key("_".join(tokens[:2])))
    return aliases


def _normalize_subject_key(text: str) -> str:
    normalized = re.sub(r"[^\w]+", "_", text.casefold(), flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return "unknown"
    if len(normalized) > 120:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        normalized = f"{normalized[:96].rstrip('_')}_{digest}"
    return normalized


def _subject_summary_text(
    *,
    resolved_subject: str,
    family: str,
    latest_extraction: dict[str, object],
    coverage: dict[str, object],
) -> str:
    facts = _fact_lines_from_extraction(dict(latest_extraction.get("payload", {})))
    coverage_hint = ""
    if coverage:
        coverage_hint = f" coverage={coverage.get('dominant_issue', 'none')}"
    facts_text = "; ".join(facts[:5]) if facts else "no extracted facts"
    return f"{resolved_subject or 'unknown subject'} [{family or 'n/a'}]{coverage_hint}: {facts_text}"


def _extraction_summary_text(task_id: str, extraction: dict[str, object], subject_key: str, family: str) -> str:
    payload = extraction.get("payload", {})
    facts = _fact_lines_from_extraction(dict(payload))
    facts_text = "; ".join(facts[:4]) if facts else "empty extraction"
    return f"{subject_key} / {family or 'n/a'} / attempt {extraction.get('attempt', '?')}: {facts_text}"


def _fact_lines_from_extraction(payload: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for key, value in payload.items():
        if key in {"family", "schema", "prompt", "locale", "status", "reason"}:
            continue
        lines.append(f"{key}: {_summarize_value(value)}")
    return lines


def _summarize_value(value: object) -> str:
    if isinstance(value, dict):
        items = list(value.items())[:4]
        return ", ".join(f"{key}={_summarize_value(val)}" for key, val in items)
    if isinstance(value, list):
        return ", ".join(_summarize_value(item) for item in value[:4])
    return str(value)


def _memory_record(
    *,
    record_type: str,
    memory_type: str,
    artifact_id: str,
    task_id: str,
    profile_key: str,
    subject_key: str,
    family: str,
    summary: str,
    payload: dict[str, object],
) -> dict[str, object]:
    embedding = _embedding_record(memory_type, summary, payload)
    return {
        "record_type": record_type,
        "memory_type": memory_type,
        "artifact_id": artifact_id,
        "task_id": task_id,
        "profile_key": profile_key,
        "subject_key": subject_key,
        "family": family,
        "summary": summary,
        "payload": payload,
        "embedding": embedding,
        "conflict_columns": ("profile_key",) if record_type == "user_profile" else ("artifact_id",),
    }


def _stable_memory_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("::".join([prefix, *parts]).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:24]}"


def _embedding_record(memory_type: str, summary: str, payload: dict[str, object]) -> dict[str, object]:
    text = _embedding_text(memory_type, summary, payload)
    return embedding_record(text)


def _embedding_from_record(record: dict[str, object]) -> list[float]:
    embedding = dict(record.get("embedding", {}))
    vector = embedding.get("vector")
    if isinstance(vector, list):
        return [float(item) for item in vector]
    return []


def _decode_memory_row(row: tuple[object, ...], record_type: str) -> dict[str, object]:
    if record_type == "user_profile":
        return _decode_user_profile_row(row)
    if len(row) == 9:
        artifact_id, task_id, memory_type, profile_key, subject_key, family, summary, payload, embedding = row
    else:
        artifact_id, task_id, profile_key, subject_key, family, summary, payload, embedding = row
        memory_type = ""
    decoded_payload = dict(payload) if isinstance(payload, dict) else {}
    decoded_embedding = dict(embedding) if isinstance(embedding, dict) else {}
    return {
        "record_type": record_type,
        "memory_type": decoded_payload.get("memory_type", memory_type or record_type),
        "artifact_id": artifact_id,
        "task_id": task_id,
        "profile_key": profile_key,
        "subject_key": subject_key,
        "family": family,
        "summary": summary,
        "payload": decoded_payload,
        "embedding": decoded_embedding,
    }


def _decode_memory_record(record: dict[str, object]) -> dict[str, object]:
    payload = dict(record.get("payload", {}))
    embedding = dict(record.get("embedding", {}))
    return {
        "record_type": str(record.get("record_type", "memory_document")),
        "memory_type": str(record.get("memory_type", record.get("record_type", "memory_document"))),
        "artifact_id": str(record.get("artifact_id", "")),
        "task_id": str(record.get("task_id", "")),
        "profile_key": str(record.get("profile_key", "")),
        "subject_key": str(record.get("subject_key", "")),
        "family": str(record.get("family", "")),
        "summary": str(record.get("summary", "")),
        "payload": payload,
        "embedding": embedding,
    }


def _decode_user_profile_row(row: tuple[object, ...]) -> dict[str, object]:
    profile_key, artifact_id, summary, payload, embedding = row
    decoded_payload = dict(payload) if isinstance(payload, dict) else {}
    decoded_embedding = dict(embedding) if isinstance(embedding, dict) else {}
    return {
        "record_type": "user_profile",
        "memory_type": "user_profile",
        "profile_key": profile_key,
        "artifact_id": artifact_id,
        "task_id": "",
        "subject_key": str(decoded_payload.get("subject_counts", {})) or str(profile_key),
        "family": str(decoded_payload.get("top_families", [""])[0]) if decoded_payload.get("top_families") else "",
        "summary": summary,
        "payload": decoded_payload,
        "embedding": decoded_embedding,
    }


def _memory_record_matches_subject(record: dict[str, object], subject_key: str) -> bool:
    normalized = _normalize_subject_key(subject_key)
    record_subject = _normalize_subject_key(str(record.get("subject_key", "")))
    if normalized == record_subject:
        return True
    payload = dict(record.get("payload", {}))
    aliases = {record_subject}
    aliases.update(_normalize_subject_key(str(alias)) for alias in payload.get("subject_aliases", []) if alias)
    return normalized in {alias for alias in aliases if alias and alias != "unknown"}


def _rank_memory_records(
    query: str,
    records: list[dict[str, object]],
    *,
    limit: int,
    memory_type: str | None = None,
) -> list[dict[str, object]]:
    active_embedder = embedder_from_env()
    query_embedding = list(embed_text(query, active_embedder))
    query_algorithm = getattr(active_embedder, "algorithm", "hash_vector_v1")
    normalized_query = _normalize_subject_key(query)
    query_aliases = _split_subject_aliases(query)
    subject_matched_records = [
        record
        for record in records
        if _record_subject_aliases(record).intersection(query_aliases)
    ]
    candidate_records = subject_matched_records or records
    ranked: list[dict[str, object]] = []
    for record in candidate_records:
        if memory_type is None and record.get("record_type") == "task_memory_context":
            continue
        embedding = dict(record.get("embedding", {}))
        if embedding.get("algorithm", "hash_vector_v1") != query_algorithm:
            continue
        base_score = cosine_similarity(query_embedding, _embedding_from_record(record))
        score = base_score
        score += _subject_boost_for_record(record, normalized_query, query_aliases)
        score += _memory_type_boost(record)
        score += _status_boost(record)
        score += _lexical_overlap_boost(record, query_aliases)
        if score <= 0:
            continue
        ranked.append({**record, "score": round(score, 6)})
    ranked.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("task_id", "")), str(item.get("artifact_id", ""))))
    return ranked[:limit]


def _subject_boost_for_record(record: dict[str, object], normalized_query: str, query_aliases: set[str]) -> float:
    if not normalized_query or normalized_query == "unknown":
        return 0.0
    aliases = _record_subject_aliases(record)
    if normalized_query in aliases:
        return 0.45
    if any(alias in query_aliases for alias in aliases):
        return 0.1
    return 0.0


def _memory_type_boost(record: dict[str, object]) -> float:
    memory_type = str(record.get("memory_type", ""))
    weights = {
        "subject_memory": 0.12,
        "task_summary": 0.08,
        "extraction_snapshot": 0.02,
        "task_memory_context": -0.08,
    }
    return weights.get(memory_type, 0.0)


def _status_boost(record: dict[str, object]) -> float:
    payload = dict(record.get("payload", {}))
    status = str(payload.get("status", ""))
    reason = str(payload.get("reason", ""))
    boost = 0.0
    if status == "success":
        boost += 0.05
    elif status == "failed":
        boost -= 0.12
    if reason == "complete":
        boost += 0.04
    elif reason in {"llm_error", "runtime_exception", "provider_execution_failed"}:
        boost -= 0.08
    return boost


def _lexical_overlap_boost(record: dict[str, object], query_aliases: set[str]) -> float:
    if not query_aliases:
        return 0.0
    haystacks = {
        str(record.get("summary", "")).casefold(),
        str(record.get("family", "")).casefold(),
    }
    payload = dict(record.get("payload", {}))
    haystacks.add(str(payload.get("resolved_subject", "")).casefold())
    haystacks.add(str(payload.get("prompt", "")).casefold())
    matches = 0
    for alias in query_aliases:
        alias_text = alias.replace("_", " ").strip()
        if not alias_text:
            continue
        if any(alias_text in haystack for haystack in haystacks if haystack):
            matches += 1
    return min(0.08, matches * 0.02)


def _record_subject_aliases(record: dict[str, object]) -> set[str]:
    payload = dict(record.get("payload", {}))
    aliases = {_normalize_subject_key(str(record.get("subject_key", "")))}
    aliases.update(_normalize_subject_key(str(alias)) for alias in payload.get("subject_aliases", []) if alias)
    resolved_subject = str(payload.get("resolved_subject", ""))
    if resolved_subject:
        aliases.update(_split_subject_aliases(resolved_subject))
    return {alias for alias in aliases if alias and alias != "unknown"}


def _payload_text(payload: dict[str, object]) -> str:
    fragments: list[str] = []

    def visit(value: object) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in {"embedding", "vector"}:
                    continue
                visit(inner)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        fragments.append(str(value))

    visit(payload)
    return " ".join(fragment for fragment in fragments if fragment)


def _embedding_text(memory_type: str, summary: str, payload: dict[str, object]) -> str:
    lines = [summary]
    resolved_subject = str(payload.get("resolved_subject", "")).strip()
    family = str(payload.get("family", "")).strip()
    if resolved_subject:
        lines.append(f"subject: {resolved_subject}")
    if family:
        lines.append(f"family: {family}")

    if memory_type == "task_summary":
        prompt = _truncate_text(str(payload.get("prompt", "")).strip(), 320)
        if prompt:
            lines.append(f"prompt: {prompt}")
        facts = _fact_lines_from_extraction(dict(payload.get("latest_extraction", {}).get("payload", {})))
        if facts:
            lines.append(f"facts: {'; '.join(facts[:5])}")
        coverage = dict(payload.get("coverage", {}))
        if coverage.get("dominant_issue"):
            lines.append(f"coverage: {coverage['dominant_issue']}")
    elif memory_type == "subject_memory":
        facts = [str(item) for item in payload.get("facts", []) if item]
        if facts:
            lines.append(f"facts: {'; '.join(facts[:6])}")
        coverage = dict(payload.get("coverage", {}))
        if coverage.get("dominant_issue"):
            lines.append(f"coverage: {coverage['dominant_issue']}")
    elif memory_type == "extraction_snapshot":
        extraction_payload = dict(payload.get("payload", {}))
        facts = _fact_lines_from_extraction(extraction_payload)
        if facts:
            lines.append(f"facts: {'; '.join(facts[:5])}")
        attempt = payload.get("attempt")
        if attempt is not None:
            lines.append(f"attempt: {attempt}")
        status = str(payload.get("status", "")).strip()
        if status:
            lines.append(f"status: {status}")
    elif memory_type == "task_memory_context":
        for key in ("intent", "task_shape", "status", "reason"):
            value = str(payload.get(key, "")).strip()
            if value:
                lines.append(f"{key}: {value}")
        event_kinds = [str(item.get("kind", "")) for item in payload.get("events", []) if item]
        if event_kinds:
            lines.append(f"events: {', '.join(event_kinds[:5])}")
    elif memory_type == "user_profile":
        top_subjects = [str(item) for item in payload.get("top_subjects", []) if item]
        top_families = [str(item) for item in payload.get("top_families", []) if item]
        if top_subjects:
            lines.append(f"top_subjects: {', '.join(top_subjects[:5])}")
        if top_families:
            lines.append(f"top_families: {', '.join(top_families[:5])}")
    else:
        lines.append(_truncate_text(_payload_text(payload), 400))

    return "\n".join(line for line in lines if line)


def _truncate_text(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
