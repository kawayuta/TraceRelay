from __future__ import annotations

from tracerelay.indexer.loader import TaskRuntimeProjector
from tracerelay.models import TaskSpec
from tracerelay.task_flow import JsonlArtifactStore
from tracerelay.task_runtime import TaskRuntime
from tracerelay.web.repository import PostgresTaskRepository, TaskRepository


class _RecordingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql, params=()):  # noqa: ANN001
        self.calls.append((str(sql), tuple(params)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = _RecordingCursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


def _run_two_tasks(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store)
    google = runtime.run_task(TaskSpec(prompt="Googleの事業内容を構造化して整理して"))
    macross = runtime.run_task(TaskSpec(prompt="Macrossについて構造化して整理して"))
    return store, google, macross


def test_memory_projection_and_jsonl_repository_support_lookup(fake_llm, tmp_path):
    store, google, macross = _run_two_tasks(fake_llm, tmp_path)

    projector = TaskRuntimeProjector(store)
    assert "CREATE TABLE IF NOT EXISTS memory_document" in projector.schema_sql()
    assert "CREATE TABLE IF NOT EXISTS task_memory_context" in projector.schema_sql()
    assert "CREATE TABLE IF NOT EXISTS user_profile" in projector.schema_sql()

    rows = projector.rows_for_task(google.task_id)
    assert any(row.table == "memory_document" and row.values["memory_type"] == "task_summary" for row in rows)
    assert any(row.table == "task_memory_context" for row in rows)
    assert not any(row.table == "user_profile" for row in rows)

    plan = projector.build_reindex_plan()
    assert any(row.table == "user_profile" for row in plan)
    assert sum(1 for row in plan if row.table == "user_profile") == 1

    repository = TaskRepository(store)
    documents = repository.list_memory_documents(subject_key="Google")
    assert any(doc["memory_type"] == "subject_memory" for doc in documents)
    assert any(doc["record_type"] == "task_memory_context" for doc in documents)
    assert any(doc["subject_key"] == "google" for doc in documents)

    search_results = repository.search_memory("leadership", limit=5)
    assert search_results
    assert search_results[0]["score"] >= search_results[-1]["score"]

    google_search = repository.search_memory("Google", limit=5)
    assert google_search[0]["subject_key"] == "google"
    assert google_search[0]["memory_type"] in {"subject_memory", "task_summary", "extraction_snapshot"}

    context = repository.get_task_memory_context(google.task_id)
    assert context["record_type"] == "task_memory_context"
    assert context["payload"]["resolved_subject"] == "Google"

    profiles = repository.list_user_profiles()
    assert len(profiles) == 1
    assert profiles[0]["profile_key"] == "default"
    assert profiles[0]["payload"]["task_count"] == 2

    profile = repository.get_user_profile("default")
    assert profile["payload"]["task_count"] == 2

    subject_bundle = repository.get_subject_memory("Google")
    assert subject_bundle["memory_documents"]
    assert subject_bundle["task_memory_contexts"]
    assert subject_bundle["profiles"]
    assert subject_bundle["profiles"][0]["profile_key"] == "default"


def test_projector_apply_schema_uses_advisory_lock(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    projector = TaskRuntimeProjector(store)
    connection = _RecordingConnection()

    projector.apply_schema(connection)

    assert connection.commits == 1
    assert connection.cursor_instance.calls[0] == ("SELECT pg_advisory_xact_lock(%s, %s)", (48251, 3003))
    assert "CREATE TABLE IF NOT EXISTS task_artifact" in connection.cursor_instance.calls[1][0]


def test_postgres_memory_queries_are_readable_from_projection_rows():
    memory_document_rows = [
        (
            "memory-1",
            "task-1",
            "default",
            "google",
            "organization",
            "Google summary",
            {
                "memory_type": "task_summary",
                "subject_aliases": ["google", "google_inc"],
            },
            {"algorithm": "hash_vector_v1", "dimensions": 48, "vector": [1.0, 0.0, 0.0]},
        ),
        (
            "memory-2",
            "task-1",
            "default",
            "google",
            "organization",
            "Google subject memory",
            {
                "memory_type": "subject_memory",
                "subject_aliases": ["google", "google_inc"],
            },
            {"algorithm": "hash_vector_v1", "dimensions": 48, "vector": [0.0, 1.0, 0.0]},
        ),
    ]
    context_rows = [
        (
            "context-1",
            "task-1",
            "default",
            "google",
            "organization",
            "Google task context",
            {
                "memory_type": "task_memory_context",
                "subject_aliases": ["google", "google_inc"],
            },
            {"algorithm": "hash_vector_v1", "dimensions": 48, "vector": [0.0, 0.0, 1.0]},
        ),
    ]
    profile_rows = [
        (
            "default",
            "profile-1",
            "Profile default: 1 task(s), families organization, subjects Google",
            {
                "profile_key": "default",
                "task_count": 1,
                "task_ids": ["task-1"],
                "family_counts": {"organization": 1},
                "subject_counts": {"Google": 1},
                "preferred_locale": "ja",
                "top_subjects": ["Google"],
                "top_families": ["organization"],
                "top_requested_fields": ["overview"],
                "top_requested_relations": [],
                "summary": "Profile default: 1 task(s), families organization, subjects Google",
            },
            {"algorithm": "hash_vector_v1", "dimensions": 48, "vector": [0.25, 0.25, 0.25]},
        ),
    ]

    def fake_fetchall(sql, params=()):  # noqa: ANN001
        if "FROM memory_document" in sql:
            rows = list(memory_document_rows)
            if "profile_key = %s" in sql:
                rows = [row for row in rows if row[2] == params[0]]
            if "subject_key = %s" in sql:
                subject = params[-1]
                rows = [row for row in rows if row[3] == subject]
            if "memory_type = %s" in sql:
                memory_type = params[-1]
                rows = [row for row in rows if row[6].get("memory_type") == memory_type]
            return rows
        if "FROM task_memory_context" in sql and "WHERE task_id = %s" in sql:
            task_id = params[0]
            return [row for row in context_rows if row[1] == task_id]
        if "FROM task_memory_context" in sql:
            rows = list(context_rows)
            if "profile_key = %s" in sql:
                rows = [row for row in rows if row[2] == params[0]]
            if "subject_key = %s" in sql:
                subject = params[-1]
                rows = [row for row in rows if row[3] == subject]
            return rows
        if "FROM user_profile" in sql and "WHERE profile_key = %s" in sql:
            profile_key = params[0]
            return [row for row in profile_rows if row[0] == profile_key]
        if "FROM user_profile" in sql:
            return list(profile_rows)
        return []

    repository = PostgresTaskRepository(connection_factory=lambda: object())
    repository._fetchall = fake_fetchall  # type: ignore[method-assign]

    documents = repository.list_memory_documents(subject_key="Google")
    assert len(documents) == 3
    assert {doc["record_type"] for doc in documents} == {"memory_document", "task_memory_context"}

    search = repository.search_memory("Google", limit=2)
    assert len(search) == 2
    assert search[0]["score"] >= search[1]["score"]
    assert search[0]["subject_key"] == "google"
    assert search[0]["memory_type"] != "task_memory_context"

    context = repository.get_task_memory_context("task-1")
    assert context["record_type"] == "task_memory_context"

    profile = repository.get_user_profile("default")
    assert profile["profile_key"] == "default"
    assert profile["payload"]["task_count"] == 1

    subject_bundle = repository.get_subject_memory("Google")
    assert len(subject_bundle["memory_documents"]) == 2
    assert len(subject_bundle["task_memory_contexts"]) == 1
    assert subject_bundle["profiles"][0]["profile_key"] == "default"


def test_search_memory_prefers_exact_subject_matches_over_prompt_noise():
    aspi_rows = [
        (
            "memory-aspi",
            "task-aspi",
            "default",
            "aspi",
            "organization",
            "ASPI summary",
            {
                "memory_type": "subject_memory",
                "resolved_subject": "ASPI",
                "subject_aliases": ["aspi"],
                "prompt": "ASPI update",
            },
            {"algorithm": "hash_vector_v1", "dimensions": 48, "vector": [1.0, 0.0, 0.0]},
        ),
    ]
    noisy_rows = [
        (
            "memory-elon",
            "task-elon",
            "default",
            "elon_musk",
            "organization",
            "Elon summary mentioning ASPI",
            {
                "memory_type": "subject_memory",
                "resolved_subject": "Elon Musk",
                "subject_aliases": ["elon_musk", "elon"],
                "prompt": "Elon Musk compared against ASPI in passing",
            },
            {"algorithm": "hash_vector_v1", "dimensions": 48, "vector": [0.99, 0.0, 0.0]},
        ),
    ]

    def fake_fetchall(sql, params=()):  # noqa: ANN001
        if "FROM memory_document" in sql:
            return list(aspi_rows + noisy_rows)
        if "FROM task_memory_context" in sql:
            return []
        if "FROM user_profile" in sql:
            return []
        return []

    repository = PostgresTaskRepository(connection_factory=lambda: object())
    repository._fetchall = fake_fetchall  # type: ignore[method-assign]

    results = repository.search_memory("ASPI", limit=5)

    assert results
    assert results[0]["task_id"] == "task-aspi"
    assert all(item["task_id"] != "task-elon" for item in results)
