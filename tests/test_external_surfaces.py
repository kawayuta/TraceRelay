from __future__ import annotations

import anyio
import json
import os
import socket
import time
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from tracerelay.config import DEFAULT_POSTGRES_DSN
from tracerelay.indexer.loader import TaskRuntimeProjector
from tracerelay.llm import (
    GeminiClient,
    GeminiConfig,
    GeminiStructuredLLM,
    LMStudioClient,
    LMStudioConfig,
    LMStudioStructuredLLM,
    OpenAIClient,
    OpenAIConfig,
    OpenAIStructuredLLM,
    OllamaClient,
    OllamaConfig,
    OllamaStructuredLLM,
    _task_extraction_schema,
    llm_from_env,
)
from tracerelay.mcp.server import LocalMCPServer, create_mcp_server
from tracerelay.models import ArtifactRecord, ExtractionResult, SchemaVersion, TaskSpec
from tracerelay.schema_store import ArtifactSchemaStore
from tracerelay.task_flow import JsonlArtifactStore
from tracerelay.task_runtime import TaskRuntime
from tracerelay.web.app import build_task_dashboard, create_app
from tracerelay.web.repository import PostgresTaskRepository, TaskRepository


class _RecordingTaskRepository:
    def __init__(self, inner: TaskRepository) -> None:
        self.inner = inner
        self.search_calls: list[dict[str, object]] = []

    def __getattr__(self, name: str) -> object:
        return getattr(self.inner, name)

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
        profile_key: str | None = None,
        subject_key: str | None = None,
        memory_type: str | None = None,
    ) -> list[dict[str, object]]:
        self.search_calls.append(
            {
                "query": query,
                "limit": limit,
                "profile_key": profile_key,
                "subject_key": subject_key,
                "memory_type": memory_type,
            }
        )
        return self.inner.search_memory(
            query,
            limit=limit,
            profile_key=profile_key,
            subject_key=subject_key,
            memory_type=memory_type,
        )


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FamilyReviewSurfaceLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "Macross",
            "subject_candidates": ["Macross"],
            "family": "organization",
            "family_rationale": "The first pass kept a generic subject profile.",
            "requested_fields": ["series", "viewing_order", "characters", "staff"],
            "requested_relations": [],
            "scope_hints": ["series", "viewing_order", "characters", "staff"],
            "task_shape": "subject_analysis",
            "locale": "ja",
        }

    def review_task_interpretation(self, spec, interpretation):  # noqa: ANN001
        return {
            "family": "media_work",
            "family_rationale": "The schema shape is centered on a title, viewing order, characters, and staff.",
        }

    def build_initial_schema(self, interpretation):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": list(interpretation.requested_fields),
            "optional_fields": [],
            "relations": [],
            "rationale": "Use the reviewed family for the initial schema.",
        }

    def evolve_schema(self, interpretation, schema, coverage, extraction):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": list(schema.required_fields),
            "optional_fields": list(schema.optional_fields),
            "relations": list(schema.relations),
            "rationale": "No-op evolution.",
        }

    def extract_task(self, family, interpretation, schema, attempt):  # noqa: ANN001
        return ExtractionResult(
            payload={
                "series": ["main series"],
                "viewing_order": ["release order"],
                "characters": ["lead character"],
                "staff": ["key staff"],
            },
            status="success",
            provider_metadata={"provider": "family-review-surface-test", "attempt": attempt},
        )


class _FamilyProbeSurfaceLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "Macross",
            "subject_candidates": ["Macross"],
            "family": "organization",
            "family_rationale": "The first pass stayed generic.",
            "requested_fields": ["overview", "staff"],
            "requested_relations": [],
            "scope_hints": ["overview", "staff"],
            "task_shape": "subject_analysis",
            "locale": "ja",
        }

    def review_task_interpretation(self, spec, interpretation):  # noqa: ANN001
        return {
            "family": "media_work",
            "family_rationale": "The title shape suggests media_work.",
        }

    def build_initial_schema(self, interpretation):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": ["overview", "staff"],
            "optional_fields": [],
            "relations": [],
            "rationale": "Probe schema.",
        }

    def evolve_schema(self, interpretation, schema, coverage, extraction):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": list(schema.required_fields),
            "optional_fields": list(schema.optional_fields),
            "relations": list(schema.relations),
            "rationale": "No-op evolution.",
        }

    def extract_task(self, family, interpretation, schema, attempt):  # noqa: ANN001
        return ExtractionResult(
            payload={
                "overview": "Macross overview",
                "staff": [] if family == "media_work" else ["executive staff"],
            },
            status="success",
            provider_metadata={"provider": "family-probe-surface-test", "attempt": attempt, "family": family},
        )


class _StrategySurfaceLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "ACME Hypergrid",
            "subject_candidates": ["ACME Hypergrid"],
            "family": "organization",
            "family_rationale": "The prompt requests an organization profile.",
            "requested_fields": ["overview", "regional_presence"],
            "requested_relations": ["suppliers"],
            "scope_hints": ["overview", "regional_presence", "suppliers"],
            "task_shape": "subject_analysis",
            "locale": "en",
        }

    def build_initial_schema(self, interpretation):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": ["overview"],
            "optional_fields": ["legacy_status"],
            "relations": ["old_relation"],
            "rationale": "Initial schema still carries legacy keys.",
        }

    def evolve_schema(self, interpretation, schema, coverage, extraction):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": ["overview", "regional_presence"],
            "optional_fields": ["legacy_status"],
            "relations": ["old_relation", "suppliers"],
            "deprecated_fields": ["legacy_status"],
            "deprecated_relations": ["old_relation"],
            "pruning_hints": ["drop legacy status from future probes"],
            "rationale": "Add the missing keys and mark legacy slots as deprecated.",
        }

    def extract_task(self, family, interpretation, schema, attempt):  # noqa: ANN001
        if attempt == 1:
            return ExtractionResult(
                payload={
                    "overview": "ACME Hypergrid overview",
                    "legacy_status": "legacy",
                    "old_relation": ["legacy relation"],
                },
                status="success",
                provider_metadata={"provider": "strategy-surface-test", "attempt": attempt},
            )
        return ExtractionResult(
            payload={
                "overview": "ACME Hypergrid overview",
                "regional_presence": ["US", "JP"],
                "suppliers": ["Supply partner"],
            },
            status="success",
            provider_metadata={"provider": "strategy-surface-test", "attempt": attempt},
        )


class _SlowSurfaceLLM:
    def __init__(self, delay_s: float = 0.05) -> None:
        self.delay_s = delay_s

    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "Slow Corp",
            "subject_candidates": ["Slow Corp"],
            "family": "organization",
            "family_rationale": "The prompt requests a company profile.",
            "requested_fields": ["overview"],
            "requested_relations": [],
            "scope_hints": ["overview"],
            "task_shape": "subject_analysis",
            "locale": "en",
        }

    def build_initial_schema(self, interpretation):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": ["overview"],
            "optional_fields": [],
            "relations": [],
            "rationale": "Initial schema.",
        }

    def evolve_schema(self, interpretation, schema, coverage, extraction):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": list(schema.required_fields),
            "optional_fields": list(schema.optional_fields),
            "relations": list(schema.relations),
            "rationale": "No-op evolution.",
        }

    def extract_task(self, family, interpretation, schema, attempt):  # noqa: ANN001
        time.sleep(self.delay_s)
        return ExtractionResult(
            payload={"overview": "Slow Corp overview"},
            status="success",
            provider_metadata={"provider": "slow-surface-test", "attempt": attempt},
        )


def _fake_urlopen(req, timeout=None):  # noqa: ANN001
    payload = json.loads(req.data.decode("utf-8"))
    system_prompt = payload["messages"][0]["content"]
    if "TASK_INTERPRETATION" in system_prompt:
        content = {
            "intent": "investigate_subject",
            "resolved_subject": "ACME Hypergrid",
            "subject_candidates": ["ACME Hypergrid"],
            "family": "organization",
            "family_rationale": "The prompt requests an organization profile.",
            "requested_fields": ["overview", "business_lines"],
            "requested_relations": [],
            "scope_hints": ["overview", "business_lines"],
            "task_shape": "subject_analysis",
            "locale": "en",
        }
    elif "INITIAL_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": [],
            "relations": [],
            "rationale": "Initial organization schema.",
        }
    elif "EVOLVE_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": ["leadership"],
            "relations": [],
            "rationale": "Add leadership if needed.",
        }
    else:
        content = {
            "payload": {
                "overview": "ACME Hypergrid organization profile",
                "business_lines": ["grid control", "monitoring"],
            },
            "status": "success",
        }
    raw = {"choices": [{"message": {"content": json.dumps(content)}}]}
    return _FakeHTTPResponse(raw)


def _fake_fenced_urlopen(req, timeout=None):  # noqa: ANN001
    payload = json.loads(req.data.decode("utf-8"))
    system_prompt = payload["messages"][0]["content"]
    if "TASK_INTERPRETATION" not in system_prompt:
        raise AssertionError("fenced response helper is only for interpretation")
    content = """```json
{
  "intent": "investigate_subject",
  "resolved_subject": "ASPI",
  "subject_candidates": ["ASPI"],
  "family": "organization",
  "family_rationale": "The prompt asks for a company analysis.",
  "requested_fields": ["overview", "business_lines"],
  "requested_relations": [],
  "scope_hints": ["overview", "business_lines"],
  "task_shape": "subject_analysis",
  "locale": "ja"
}
```"""
    raw = {"choices": [{"message": {"content": content}}]}
    return _FakeHTTPResponse(raw)


def _fake_reasoning_content_urlopen(req, timeout=None):  # noqa: ANN001
    payload = json.loads(req.data.decode("utf-8"))
    system_prompt = payload["messages"][0]["content"]
    if "TASK_INTERPRETATION" not in system_prompt:
        raise AssertionError("reasoning response helper is only for interpretation")
    content = {
        "intent": "investigate_subject",
        "resolved_subject": "ASPI",
        "subject_candidates": ["ASPI"],
        "family": "deep_research_target",
        "family_rationale": "The prompt names a subject that needs deeper structured research.",
        "requested_fields": ["overview", "business_lines"],
        "requested_relations": ["subsidiaries"],
        "scope_hints": ["overview", "business_lines", "subsidiaries"],
        "task_shape": "subject_analysis",
        "locale": "ja",
    }
    raw = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": json.dumps(content),
                }
            }
        ]
    }
    return _FakeHTTPResponse(raw)


def _fake_ollama_urlopen(req, timeout=None):  # noqa: ANN001
    assert req.full_url.endswith("/api/chat")
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["model"] == "ollama-local-model"
    assert payload["format"]["type"] == "object"
    system_prompt = payload["messages"][0]["content"]
    if "TASK_INTERPRETATION" in system_prompt:
        content = {
            "intent": "investigate_subject",
            "resolved_subject": "ACME Hypergrid",
            "subject_candidates": ["ACME Hypergrid"],
            "family": "organization",
            "family_rationale": "The prompt requests an organization profile.",
            "requested_fields": ["overview", "business_lines"],
            "requested_relations": [],
            "scope_hints": ["overview", "business_lines"],
            "task_shape": "subject_analysis",
            "locale": "en",
        }
    elif "INITIAL_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": [],
            "relations": [],
            "rationale": "Initial organization schema.",
        }
    elif "EVOLVE_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": ["leadership"],
            "relations": [],
            "rationale": "Add leadership if needed.",
        }
    else:
        content = {
            "payload": {
                "overview": "ACME Hypergrid organization profile",
                "business_lines": ["grid control", "monitoring"],
            },
            "status": "success",
        }
    raw = {
        "model": payload["model"],
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": json.dumps(content)},
    }
    return _FakeHTTPResponse(raw)


def _fake_openai_urlopen(req, timeout=None):  # noqa: ANN001
    assert req.full_url.endswith("/v1/chat/completions")
    assert req.headers["Authorization"] == "Bearer test-openai-key"
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["model"] == "gpt-4.1-mini"
    system_prompt = payload["messages"][0]["content"]
    if "TASK_INTERPRETATION" in system_prompt:
        content = {
            "intent": "investigate_subject",
            "resolved_subject": "ACME Hypergrid",
            "subject_candidates": ["ACME Hypergrid"],
            "family": "organization",
            "family_rationale": "The prompt requests an organization profile.",
            "requested_fields": ["overview", "business_lines"],
            "requested_relations": [],
            "scope_hints": ["overview", "business_lines"],
            "task_shape": "subject_analysis",
            "locale": "en",
        }
    elif "INITIAL_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": [],
            "relations": [],
            "rationale": "Initial organization schema.",
        }
    elif "EVOLVE_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": ["leadership"],
            "relations": [],
            "rationale": "Add leadership if needed.",
        }
    else:
        content = {
            "payload": {
                "overview": "ACME Hypergrid organization profile",
                "business_lines": ["grid control", "monitoring"],
            },
            "status": "success",
        }
    raw = {"choices": [{"message": {"content": json.dumps(content)}}]}
    return _FakeHTTPResponse(raw)


def _fake_gemini_urlopen(req, timeout=None):  # noqa: ANN001
    assert ":generateContent?" in req.full_url
    assert "key=test-gemini-key" in req.full_url
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["responseJsonSchema"]["type"] == "object"
    system_prompt = payload["systemInstruction"]["parts"][0]["text"]
    if "TASK_INTERPRETATION" in system_prompt:
        content = {
            "intent": "investigate_subject",
            "resolved_subject": "ACME Hypergrid",
            "subject_candidates": ["ACME Hypergrid"],
            "family": "organization",
            "family_rationale": "The prompt requests an organization profile.",
            "requested_fields": ["overview", "business_lines"],
            "requested_relations": [],
            "scope_hints": ["overview", "business_lines"],
            "task_shape": "subject_analysis",
            "locale": "en",
        }
    elif "INITIAL_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": [],
            "relations": [],
            "rationale": "Initial organization schema.",
        }
    elif "EVOLVE_SCHEMA" in system_prompt:
        content = {
            "family": "organization",
            "required_fields": ["overview", "business_lines"],
            "optional_fields": ["leadership"],
            "relations": [],
            "rationale": "Add leadership if needed.",
        }
    else:
        content = {
            "payload": {
                "overview": "ACME Hypergrid organization profile",
                "business_lines": ["grid control", "monitoring"],
            },
            "status": "success",
        }
    raw = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(content)}],
                },
                "finishReason": "STOP",
            }
        ]
    }
    return _FakeHTTPResponse(raw)


def _timeout_urlopen(req, timeout=None):  # noqa: ANN001
    raise socket.timeout("timed out")


def test_jsonl_store_projection_web_and_mcp(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store)
    google = runtime.run_task(
        TaskSpec(
            prompt="Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して"
        )
    )
    policy = runtime.run_task(
        TaskSpec(
            prompt="日本の少子化対策の政策パッケージを、政策目的、対象人口、実施主体、施策一覧、財源、評価指標、論点で構造化して"
        )
    )

    assert store.path.exists()
    assert set(store.list_task_ids()) == {google.task_id, policy.task_id}

    projector = TaskRuntimeProjector(store)
    schema_sql = projector.schema_sql()
    assert "CREATE TABLE IF NOT EXISTS schema_version" in schema_sql
    rows = projector.rows_for_task(google.task_id)
    assert {row.table for row in rows} >= {
        "task_artifact",
        "task_prompt",
        "task_interpretation",
        "task_run",
        "schema_version",
        "task_extraction",
        "coverage_report",
        "task_schema_candidate_map",
    }

    repository = TaskRepository(store)
    app = create_app(repository)
    client = app.test_client()
    tasks = client.get("/api/tasks")
    assert tasks.status_code == 200
    assert len(tasks.get_json()) == 2
    html_index = client.get("/tasks")
    assert html_index.status_code == 200
    assert "Task Dashboard" in html_index.get_data(as_text=True)
    task_detail = client.get(f"/api/tasks/{google.task_id}")
    assert task_detail.status_code == 200
    assert task_detail.get_json()["interpretation"]["family"] == "organization"
    task_trace = client.get(f"/api/tasks/{google.task_id}/trace")
    assert task_trace.status_code == 200
    trace_payload = task_trace.get_json()
    assert trace_payload["summary"]["family"] == "organization"
    assert trace_payload["flowchart"]["nodes"][0]["artifact_type"] == "task_prompt"
    assert "Execution Loop" in [child["title"] for child in trace_payload["decision_tree"]["children"]]
    task_schema = client.get(f"/api/tasks/{google.task_id}/schema")
    assert task_schema.status_code == 200
    assert task_schema.get_json()["active_schema"]["version"] == 2
    trace_page = client.get(f"/tasks/{google.task_id}")
    assert trace_page.status_code == 200
    trace_html = trace_page.get_data(as_text=True)
    assert "Execution tree" in trace_html
    assert "Artifact Ledger" in trace_html
    assert "Google" in trace_html

    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    description = server.describe()
    assert isinstance(server.fastmcp, FastMCP)
    assert {tool["name"] for tool in description["tools"]} >= {
        "task_evolve",
        "task_status",
        "continue_prior_work",
        "structure_subject",
        "inspect_latest_changes",
        "analyze_information_gaps",
        "prepare_search_queries",
        "plan_next_step",
        "task_trace",
        "schema_status",
        "schema_apply",
        "artifact_read",
        "artifact_search",
    }
    assert {tool.name for tool in server.list_tools()} >= {
        "task_evolve",
        "task_status",
        "continue_prior_work",
        "structure_subject",
        "inspect_latest_changes",
        "analyze_information_gaps",
        "prepare_search_queries",
        "plan_next_step",
        "task_trace",
        "schema_status",
        "schema_apply",
        "artifact_read",
        "artifact_search",
    }
    assert "tracerelay://tasks" in {
        str(resource.uri) for resource in server.list_resources()
    }
    assert "tracerelay://tasks/{task_id}" in {
        str(resource.uriTemplate) for resource in server.list_resource_templates()
    }
    assert "tracerelay://tasks/{task_id}/trace" in {
        str(resource.uriTemplate) for resource in server.list_resource_templates()
    }
    assert "tracerelay://tasks/{task_id}/gaps" in {
        str(resource.uriTemplate) for resource in server.list_resource_templates()
    }
    assert "tracerelay://tasks/{task_id}/queries" in {
        str(resource.uriTemplate) for resource in server.list_resource_templates()
    }
    assert "tracerelay://tasks/{task_id}/next-step" in {
        str(resource.uriTemplate) for resource in server.list_resource_templates()
    }
    assert {prompt.name for prompt in server.list_prompts()} >= {
        "investigate_subject",
        "compare_subjects",
        "analyze_policy",
        "analyze_incident",
    }
    assert server.read_resource("tracerelay://tasks")
    schema_status = server.call_tool("schema_status", {"task_id": google.task_id})
    assert schema_status["active_schema"]["version"] == 2
    continue_result = server.call_tool(
        "continue_prior_work",
        {
            "prompt": "Googleの事業内容の分析を継続して、前回の内容を踏まえて整理して",
            "subject": "Google",
        },
    )
    assert continue_result["recalled"]["kind"] == "subject"
    assert continue_result["run"]["task_id"] == continue_result["task_id"]
    structure_result = server.call_tool(
        "structure_subject",
        {"prompt": "Googleの事業内容を構造化して整理して"},
    )
    assert structure_result["run"]["task_id"] == structure_result["task_id"]
    latest_changes = server.call_tool("inspect_latest_changes", {"subject": "Google"})
    assert latest_changes["found"] is True
    assert latest_changes["task"]["task_id"] == latest_changes["task_id"]
    assert latest_changes["next_step"]["recommended_queries"]
    task_trace_result = server.call_tool("task_trace", {"task_id": google.task_id})
    assert task_trace_result["summary"]["family"] == "organization"
    gap_result = server.call_tool("analyze_information_gaps", {"task_id": google.task_id})
    assert gap_result["found"] is True
    assert gap_result["subject"] == "Google"
    query_result = server.call_tool("prepare_search_queries", {"task_id": google.task_id})
    assert query_result["queries"]
    next_step_result = server.call_tool("plan_next_step", {"task_id": google.task_id})
    assert next_step_result["recommended_tool"]
    apply_result = server.call_tool("schema_apply", {"task_id": google.task_id})
    assert apply_result["applied"] is True
    events = server.read_resource(f"tracerelay://tasks/{google.task_id}/events")
    assert any(event["kind"] == "schema_apply_confirmed" for event in events)
    trace_resource = server.read_resource(f"tracerelay://tasks/{google.task_id}/trace")
    assert trace_resource["summary"]["status"] == "success"
    assert server.read_resource(f"tracerelay://tasks/{google.task_id}/gaps")["subject"] == "Google"
    assert server.read_resource(f"tracerelay://tasks/{google.task_id}/queries")["queries"]
    assert server.read_resource(f"tracerelay://tasks/{google.task_id}/next-step")["recommended_actions"]
    search_results = server.call_tool("artifact_search", {"query": "Google"})
    assert search_results[0]["task_id"] == google.task_id
    assert "Google" in server.render_prompt("investigate_subject", {"subject": "Google"})

    fastmcp = create_mcp_server(runtime, store, repository=repository, sync_dsn=None)
    assert isinstance(fastmcp, FastMCP)
    prompt_result = anyio.run(fastmcp.get_prompt, "investigate_subject", {"subject": "Google"})
    assert prompt_result.messages[0].content.text.startswith("Google")
    tool_result = anyio.run(fastmcp.call_tool, "artifact_search", {"query": "Google"})
    structured_result = tool_result[1] if isinstance(tool_result, tuple) else tool_result
    if isinstance(structured_result, dict) and "result" in structured_result:
        structured_result = structured_result["result"]
    assert structured_result[0]["task_id"] == google.task_id
    trace_tool_result = anyio.run(fastmcp.call_tool, "task_trace", {"task_id": google.task_id})
    structured_trace = trace_tool_result[1] if isinstance(trace_tool_result, tuple) else trace_tool_result
    if isinstance(structured_trace, dict) and "result" in structured_trace:
        structured_trace = structured_trace["result"]
    assert structured_trace["summary"]["reason"] == "complete"


def test_memory_web_and_mcp_surfaces(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store)
    google = runtime.run_task(
        TaskSpec(
            prompt="Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して"
        )
    )
    policy = runtime.run_task(
        TaskSpec(
            prompt="日本の少子化対策の政策パッケージを、政策目的、対象人口、実施主体、施策一覧、財源、評価指標、論点で構造化して"
        )
    )

    repository = TaskRepository(store)
    app = create_app(repository)
    client = app.test_client()

    profile_payload = client.get("/api/memory/profile").get_json()
    assert profile_payload["kind"] == "profile"
    assert profile_payload["profile_id"] == "workspace"
    assert profile_payload["stats"][0]["value"] == 2

    search_payload = client.get("/api/memory/search?q=Google").get_json()
    assert search_payload["strategy"] == "hash_vector_v1"
    assert search_payload["results"][0]["task_id"] == google.task_id
    assert len({item["task_id"] for item in search_payload["results"]}) == len(search_payload["results"])

    subject_payload = client.get("/api/memory/subjects/Google").get_json()
    assert subject_payload["kind"] == "subject"
    assert subject_payload["subject"] == "Google"
    assert subject_payload["related_tasks"][0]["task_id"] == google.task_id
    assert subject_payload["learned_facts"]

    task_memory_payload = client.get(f"/api/memory/tasks/{google.task_id}").get_json()
    assert task_memory_payload["kind"] == "task"
    assert task_memory_payload["task_id"] == google.task_id
    assert "Google" in task_memory_payload["recall_context"]

    memory_html = client.get("/memory")
    assert memory_html.status_code == 200
    assert "Memory Browser" in memory_html.get_data(as_text=True)
    subject_html = client.get("/memory/subjects/Google")
    assert subject_html.status_code == 200
    assert "Subject Memory: Google" in subject_html.get_data(as_text=True)
    assert "No learned facts recorded yet." not in subject_html.get_data(as_text=True)
    task_html = client.get(f"/memory/tasks/{google.task_id}")
    assert task_html.status_code == 200
    assert "Task Snapshot" in task_html.get_data(as_text=True)

    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    description = server.describe()
    assert {tool["name"] for tool in description["tools"]} >= {
        "memory_search",
        "memory_profile",
        "subject_memory",
        "task_memory_context",
    }
    assert {tool.name for tool in server.list_tools()} >= {
        "memory_search",
        "memory_profile",
        "subject_memory",
        "task_memory_context",
    }
    assert "tracerelay://memory/profile" in {
        str(resource.uri) for resource in server.list_resources()
    }
    assert "tracerelay://memory/search/{query}" in {
        str(resource.uriTemplate) for resource in server.list_resource_templates()
    }
    memory_search_result = server.call_tool("memory_search", {"query": "Google"})
    assert memory_search_result["results"][0]["task_id"] == google.task_id
    assert len({item["task_id"] for item in memory_search_result["results"]}) == len(memory_search_result["results"])
    memory_profile_result = server.call_tool("memory_profile", {"profile_id": "workspace"})
    assert memory_profile_result["profile_id"] == "workspace"
    subject_memory_result = server.call_tool("subject_memory", {"subject": "Google"})
    assert subject_memory_result["subject"] == "Google"
    assert subject_memory_result["learned_facts"]
    task_memory_result = server.call_tool("task_memory_context", {"task_id": google.task_id})
    assert task_memory_result["task_id"] == google.task_id
    assert server.read_resource("tracerelay://memory/profile")["profile_id"] == "workspace"
    assert server.read_resource("tracerelay://memory/subjects/Google")["subject"] == "Google"
    assert server.read_resource(f"tracerelay://memory/tasks/{google.task_id}")["task_id"] == google.task_id


def test_mcp_long_running_tasks_return_pending_and_can_be_polled(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_SlowSurfaceLLM(delay_s=0.05), artifact_store=store)
    repository = TaskRepository(store)
    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None, task_wait_timeout_s=0.001)

    result = server.call_tool("task_evolve", {"prompt": "Please investigate Slow Corp."})

    assert result["pending"] is True
    assert result["status"] in {"queued", "running"}
    assert result["reason"] == "background_execution"
    assert result["job_id"]
    assert result["poll_tool"] == "task_status"

    pending_status = server.call_tool("task_status", {"job_id": result["job_id"]})
    assert pending_status["found"] is True
    assert pending_status["pending"] is True

    time.sleep(0.08)
    completed_status = server.call_tool(
        "task_status",
        {"task_id": result["task_id"], "job_id": result["job_id"]},
    )
    assert completed_status["found"] is True
    assert completed_status["pending"] is False
    assert completed_status["job_status"] == "completed"
    assert completed_status["status"] == "success"
    assert completed_status["reason"] == "complete"

    structured = server.call_tool(
        "structure_subject",
        {"prompt": "Please investigate Slow Corp.", "wait_seconds": 0.001},
    )
    assert structured["pending"] is True
    assert structured["run"]["pending"] is True
    assert structured["poll_tool"] == "task_status"


def test_memory_web_search_supports_exact_subject_scope(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store)
    google = runtime.run_task(
        TaskSpec(prompt="Googleの事業内容に加えて、主要経営陣、主要リスクも構造化して整理して")
    )

    repository = _RecordingTaskRepository(TaskRepository(store))
    app = create_app(repository)
    client = app.test_client()

    search_payload = client.get("/api/memory/search?q=leadership&subject=Google").get_json()
    assert search_payload["subject_scope"] == "Google"
    assert search_payload["results"][0]["task_id"] == google.task_id
    assert repository.search_calls[-1]["query"] == "leadership"
    assert repository.search_calls[-1]["subject_key"] == "google"

    search_html = client.get("/memory/search?q=leadership&subject=Google")
    assert search_html.status_code == 200
    search_html_text = search_html.get_data(as_text=True)
    assert 'name="subject"' in search_html_text
    assert 'value="Google"' in search_html_text
    assert "Subject scope" in search_html_text

    repository.search_calls.clear()
    subject_payload = client.get("/api/memory/subjects/Google").get_json()
    assert subject_payload["subject_scope"] == "Google"
    assert any(call["query"] == "Google" and call["subject_key"] == "google" for call in repository.search_calls)

    repository.search_calls.clear()
    task_memory_payload = client.get(f"/api/memory/tasks/{google.task_id}").get_json()
    assert task_memory_payload["subject_scope"] == "Google"
    assert any(call["query"] == "Google" and call["subject_key"] == "google" for call in repository.search_calls)


def test_inspect_latest_changes_reports_family_recheck(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_FamilyReviewSurfaceLLM(), artifact_store=store)
    run = runtime.run_task(TaskSpec(prompt="Macrossの視聴順と主要キャラと制作スタッフを整理して"))

    repository = TaskRepository(store)
    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    latest_changes = server.call_tool("inspect_latest_changes", {"task_id": run.task_id})

    assert latest_changes["found"] is True
    assert latest_changes["family_changed"] is True
    assert latest_changes["initial_family"] == "organization"
    assert latest_changes["final_family"] == "media_work"
    assert latest_changes["family_review_rationale"]
    assert latest_changes["task"]["interpretation"]["initial_family"] == "organization"
    assert any(event["kind"] == "family_revised" for event in latest_changes["events"])


def test_latest_changes_and_trace_surface_branch_decision(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store)
    run = runtime.run_task(
        TaskSpec(
            prompt="Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して"
        )
    )

    repository = TaskRepository(store)
    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    latest_changes = server.call_tool("inspect_latest_changes", {"task_id": run.task_id})

    assert latest_changes["chosen_branch_type"] == "complete"
    assert latest_changes["completion_rate"] == 1.0
    assert latest_changes["task"]["evidence_bundle"]["items"]
    assert latest_changes["task"]["latest_branch_decision"]["chosen_branch_type"] == "complete"

    trace = repository.get_task_trace(run.task_id)
    assert trace["summary"]["chosen_branch_type"] == "complete"
    assert any(node["artifact_type"] == "task_branch_decision" for node in trace["flowchart"]["nodes"])


def test_latest_changes_and_trace_surface_family_probe_selection(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_FamilyProbeSurfaceLLM(), artifact_store=store)
    run = runtime.run_task(TaskSpec(prompt="Macrossの概要とスタッフを整理して"))

    repository = TaskRepository(store)
    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    latest_changes = server.call_tool("inspect_latest_changes", {"task_id": run.task_id})

    assert latest_changes["final_family"] == "organization"
    assert latest_changes["task"]["family_selection"]["chosen_family"] == "organization"
    assert len(latest_changes["task"]["family_probes"]) == 2

    trace = repository.get_task_trace(run.task_id)
    assert trace["summary"]["selected_family"] == "organization"
    assert any(node["artifact_type"] == "task_family_selection" for node in trace["flowchart"]["nodes"])


def test_latest_changes_and_trace_surface_strategy_probe_and_schema_pruning(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_StrategySurfaceLLM(), artifact_store=store)
    run = runtime.run_task(TaskSpec(prompt="Please investigate ACME Hypergrid with regional presence and suppliers."))

    repository = TaskRepository(store)
    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    latest_changes = server.call_tool("inspect_latest_changes", {"task_id": run.task_id})

    assert latest_changes["selected_strategy"] == "schema_evolution"
    assert latest_changes["task"]["strategy_selection"]["chosen_branch_type"] == "schema_evolution"
    assert len(latest_changes["task"]["strategy_probes"]) >= 1
    assert latest_changes["task"]["schema_versions"][-1]["deprecated_fields"] == ["legacy_status"]
    assert latest_changes["task"]["schema_versions"][-1]["pruning_hints"] == ["drop legacy status from future probes"]
    assert latest_changes["telemetry"]

    trace = repository.get_task_trace(run.task_id)
    assert trace["summary"]["selected_strategy"] == "schema_evolution"
    assert trace["schema_lineage"][-1]["deprecated_fields"] == ["legacy_status"]
    assert trace["schema_lineage"][-1]["pruning_hints"] == ["drop legacy status from future probes"]
    assert any(node["artifact_type"] == "task_strategy_probe" for node in trace["flowchart"]["nodes"])
    assert any(node["artifact_type"] == "task_strategy_selection" for node in trace["flowchart"]["nodes"])
    assert "Strategy Branching" in [child["title"] for child in trace["decision_tree"]["children"]]


def test_planning_tools_surface_schema_gap_and_queries(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store, max_schema_rounds=0)
    run = runtime.run_task(
        TaskSpec(
            prompt="Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して"
        )
    )
    assert run.reason == "schema_evolution_required"

    repository = TaskRepository(store)
    app = create_app(repository)
    client = app.test_client()

    gaps = client.get(f"/api/tasks/{run.task_id}/gaps").get_json()
    assert gaps["dominant_issue"] == "schema"
    assert gaps["needs_schema_evolution"] is True
    assert gaps["missing_fields"] or gaps["missing_relations"]

    queries = client.get(f"/api/tasks/{run.task_id}/queries").get_json()
    assert queries["queries"]
    assert "Google" in queries["queries"][0]["query"]

    next_step = client.get(f"/api/tasks/{run.task_id}/next-step").get_json()
    assert next_step["recommended_tool"] == "continue_prior_work"
    assert next_step["chosen_branch_type"] == "halt_partial"
    assert any(item["tool"] == "prepare_search_queries" for item in next_step["recommended_actions"])
    assert any("task_memory_context" in item for item in next_step["pre_search_checks"])

    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    gap_result = server.call_tool("analyze_information_gaps", {"task_id": run.task_id})
    assert gap_result["dominant_issue"] == "schema"
    query_result = server.call_tool("prepare_search_queries", {"task_id": run.task_id})
    assert query_result["queries"]
    next_result = server.call_tool("plan_next_step", {"task_id": run.task_id})
    assert next_result["recommended_tool"] == "continue_prior_work"
    assert next_result["chosen_branch_type"] == "halt_partial"
    assert next_result["recommended_queries"]


def test_lm_studio_http_integration(tmp_path):
    with patch("tracerelay.llm.request.urlopen", side_effect=_fake_urlopen):
        client = LMStudioClient(
            LMStudioConfig(
                base_url="http://127.0.0.1:1234",
                model="local-model",
                timeout_s=2.0,
            )
        )
        llm = LMStudioStructuredLLM(client)
        store = JsonlArtifactStore(tmp_path / "workspace")
        runtime = TaskRuntime(llm=llm, artifact_store=store)
        run = runtime.run_task(TaskSpec(prompt="Please investigate ACME Hypergrid."))

    assert run.interpretation.resolved_subject == "ACME Hypergrid"
    assert run.interpretation.family == "organization"
    assert run.extraction.provider_metadata["provider"] == "lmstudio"
    assert run.status == "success"


def test_timeout_is_normalized_to_llm_error(tmp_path):
    with patch("tracerelay.llm.request.urlopen", side_effect=_timeout_urlopen):
        client = LMStudioClient(
            LMStudioConfig(
                base_url="http://127.0.0.1:1234",
                model="local-model",
                timeout_s=2.0,
            )
        )
        llm = LMStudioStructuredLLM(client)
        store = JsonlArtifactStore(tmp_path / "workspace")
        runtime = TaskRuntime(llm=llm, artifact_store=store)
        repository = TaskRepository(store)
        server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
        result = server.call_tool("task_evolve", {"prompt": "Please investigate ACME Hypergrid."})

    assert result["status"] == "failed"
    assert result["reason"] == "llm_error"
    assert "timed out" in result["error"]


def test_lm_studio_parses_fenced_json_response():
    with patch("tracerelay.llm.request.urlopen", side_effect=_fake_fenced_urlopen):
        client = LMStudioClient(
            LMStudioConfig(
                base_url="http://127.0.0.1:1234",
                model="local-model",
                timeout_s=2.0,
            )
        )
        llm = LMStudioStructuredLLM(client)
        payload = llm.interpret_task(TaskSpec(prompt="ASPIの事業を整理して"))

    assert payload["resolved_subject"] == "ASPI"
    assert payload["family"] == "organization"


def test_lm_studio_parses_reasoning_content_when_content_is_empty():
    with patch("tracerelay.llm.request.urlopen", side_effect=_fake_reasoning_content_urlopen):
        client = LMStudioClient(
            LMStudioConfig(
                base_url="http://127.0.0.1:1234",
                model="local-model",
                timeout_s=2.0,
            )
        )
        llm = LMStudioStructuredLLM(client)
        payload = llm.interpret_task(TaskSpec(prompt="ASPIの事業を整理して"))

    assert payload["resolved_subject"] == "ASPI"
    assert payload["family"] == "deep_research_target"


def test_ollama_http_integration(tmp_path):
    with patch("tracerelay.llm.request.urlopen", side_effect=_fake_ollama_urlopen):
        client = OllamaClient(
            OllamaConfig(
                base_url="http://127.0.0.1:11434",
                model="ollama-local-model",
                timeout_s=2.0,
            )
        )
        llm = OllamaStructuredLLM(client)
        store = JsonlArtifactStore(tmp_path / "workspace")
        runtime = TaskRuntime(llm=llm, artifact_store=store)
        run = runtime.run_task(TaskSpec(prompt="Please investigate ACME Hypergrid."))

    assert run.interpretation.resolved_subject == "ACME Hypergrid"
    assert run.interpretation.family == "organization"
    assert run.extraction.provider_metadata["provider"] == "ollama"
    assert run.status == "success"


def test_openai_http_integration(tmp_path):
    with patch("tracerelay.llm.request.urlopen", side_effect=_fake_openai_urlopen):
        client = OpenAIClient(
            OpenAIConfig(
                api_key="test-openai-key",
                model="gpt-4.1-mini",
                timeout_s=2.0,
            )
        )
        llm = OpenAIStructuredLLM(client)
        store = JsonlArtifactStore(tmp_path / "workspace")
        runtime = TaskRuntime(llm=llm, artifact_store=store)
        run = runtime.run_task(TaskSpec(prompt="Please investigate ACME Hypergrid."))

    assert run.interpretation.resolved_subject == "ACME Hypergrid"
    assert run.interpretation.family == "organization"
    assert run.extraction.provider_metadata["provider"] == "openai"
    assert run.status == "success"


def test_gemini_http_integration(tmp_path):
    with patch("tracerelay.llm.request.urlopen", side_effect=_fake_gemini_urlopen):
        client = GeminiClient(
            GeminiConfig(
                api_key="test-gemini-key",
                model="gemini-2.5-flash",
                timeout_s=2.0,
            )
        )
        llm = GeminiStructuredLLM(client)
        store = JsonlArtifactStore(tmp_path / "workspace")
        runtime = TaskRuntime(llm=llm, artifact_store=store)
        run = runtime.run_task(TaskSpec(prompt="Please investigate ACME Hypergrid."))

    assert run.interpretation.resolved_subject == "ACME Hypergrid"
    assert run.interpretation.family == "organization"
    assert run.extraction.provider_metadata["provider"] == "gemini"
    assert run.status == "success"


def test_llm_from_env_selects_ollama_provider():
    with patch.dict(
        os.environ,
        {
            "TRACERELAY_LLM_PROVIDER": "ollama",
            "TRACERELAY_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "TRACERELAY_OLLAMA_MODEL": "qwen3",
        },
        clear=True,
    ):
        llm = llm_from_env()

    assert isinstance(llm, OllamaStructuredLLM)


def test_llm_from_env_selects_openai_provider():
    with patch.dict(
        os.environ,
        {
            "TRACERELAY_LLM_PROVIDER": "openai",
            "TRACERELAY_OPENAI_API_KEY": "test-openai-key",
            "TRACERELAY_OPENAI_MODEL": "gpt-4.1-mini",
        },
        clear=True,
    ):
        llm = llm_from_env()

    assert isinstance(llm, OpenAIStructuredLLM)


def test_llm_from_env_selects_gemini_provider():
    with patch.dict(
        os.environ,
        {
            "TRACERELAY_LLM_PROVIDER": "gemini",
            "TRACERELAY_GEMINI_API_KEY": "test-gemini-key",
            "TRACERELAY_GEMINI_MODEL": "gemini-2.5-flash",
        },
        clear=True,
    ):
        llm = llm_from_env()

    assert isinstance(llm, GeminiStructuredLLM)


def test_schema_store_and_extraction_schema_deduplicate_keys(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    schema_store = ArtifactSchemaStore(store)
    schema = schema_store.create_or_update_schema(
        "task-1",
        "google",
        "organization",
        {
            "required_fields": ["overview", "leadership", "overview"],
            "optional_fields": ["leadership", "major_risks", "overview"],
            "relations": ["subsidiaries", "major_risks", "subsidiaries"],
            "deprecated_fields": ["leadership", "unknown_field", "leadership"],
            "deprecated_relations": ["subsidiaries", "missing_relation"],
            "pruning_hints": ["drop noisy legacy slots", "drop noisy legacy slots"],
            "rationale": "Normalize duplicates.",
        },
        parent=None,
    )

    assert schema.required_fields == ("overview", "leadership")
    assert schema.optional_fields == ("major_risks",)
    assert schema.relations == ("subsidiaries",)
    assert schema.deprecated_fields == ("leadership",)
    assert schema.deprecated_relations == ("subsidiaries",)
    assert schema.pruning_hints == ("drop noisy legacy slots",)

    extraction_schema = _task_extraction_schema(
        SchemaVersion(
            schema_id="schema-1",
            subject_key="google",
            family="organization",
            version=1,
            parent_schema_id=None,
            required_fields=("overview", "overview"),
            optional_fields=("major_risks", "overview"),
            relations=("subsidiaries", "major_risks", "subsidiaries"),
            rationale="test",
            deprecated_fields=("major_risks",),
            deprecated_relations=("subsidiaries",),
        )
    )
    payload_schema = extraction_schema["properties"]["payload"]
    assert list(payload_schema["properties"].keys()) == ["overview"]
    assert payload_schema["required"] == ["overview"]


class _StubCursor:
    def __init__(self, task_id: str, artifacts: list[tuple[object, ...]], summary_rows: list[tuple[object, ...]]) -> None:
        self.task_id = task_id
        self.artifacts = artifacts
        self.summary_rows = summary_rows
        self.rows: list[tuple[object, ...]] = []

    def execute(self, sql, params=()):  # noqa: ANN001
        if "FROM task_artifact" in sql:
            if not params:
                self.rows = self.summary_rows
                return
            requested_task_id = params[0]
            artifact_type = params[1] if len(params) > 1 else None
            if requested_task_id != self.task_id:
                self.rows = []
                return
            rows = self.artifacts
            if artifact_type is not None:
                rows = [row for row in rows if row[1] == artifact_type]
            self.rows = rows
            return
        self.rows = self.summary_rows

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _StubConnection:
    def __init__(self, task_id: str, artifacts: list[tuple[object, ...]], summary_rows: list[tuple[object, ...]]) -> None:
        self.task_id = task_id
        self.artifacts = artifacts
        self.summary_rows = summary_rows

    def cursor(self):
        return _StubCursor(self.task_id, self.artifacts, self.summary_rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _ExplodingLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        raise RuntimeError("simulated interpretation failure")

    def build_initial_schema(self, interpretation):  # noqa: ANN001
        raise AssertionError("not reached")

    def evolve_schema(self, interpretation, schema, coverage, extraction):  # noqa: ANN001
        raise AssertionError("not reached")

    def extract_task(self, family, interpretation, schema, attempt):  # noqa: ANN001
        raise AssertionError("not reached")


def test_mcp_task_failure_is_persisted_and_browseable(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_ExplodingLLM(), artifact_store=store)
    repository = TaskRepository(store)
    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)

    result = server.call_tool("task_evolve", {"prompt": "ASPIヘリウムの分析を進化させる"})

    assert result["status"] == "failed"
    assert result["reason"] == "runtime_exception"
    task_id = result["task_id"]

    task = repository.get_task(task_id)
    assert task["run"]["status"] == "failed"
    assert task["events"][-1]["kind"] == "task_failed"

    trace = repository.get_task_trace(task_id)
    assert trace["summary"]["status"] == "failed"
    assert trace["flowchart"]["nodes"][-1]["artifact_type"] == "task_run"


def test_task_repository_and_dashboard_sort_tasks_by_latest_processed_at(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    store.append(
        ArtifactRecord(
            artifact_id="artifact-1",
            task_id="task-older",
            artifact_type="task_prompt",
            payload={"prompt": "Older task", "locale": "en"},
            recorded_at="2026-03-31T00:00:00.000000Z",
        )
    )
    store.append(
        ArtifactRecord(
            artifact_id="artifact-2",
            task_id="task-older",
            artifact_type="task_run",
            payload={"status": "success", "reason": "complete"},
            recorded_at="2026-03-31T00:01:00.000000Z",
        )
    )
    store.append(
        ArtifactRecord(
            artifact_id="artifact-3",
            task_id="task-newer",
            artifact_type="task_prompt",
            payload={"prompt": "Newer task", "locale": "en"},
            recorded_at="2026-04-01T00:00:00.000000Z",
        )
    )
    store.append(
        ArtifactRecord(
            artifact_id="artifact-4",
            task_id="task-newer",
            artifact_type="task_run",
            payload={"status": "failed", "reason": "runtime_exception"},
            recorded_at="2026-04-01T00:02:00.000000Z",
        )
    )

    repository = TaskRepository(store)

    listed = repository.list_tasks()
    dashboard = build_task_dashboard(repository)

    assert [task["task_id"] for task in listed] == ["task-newer", "task-older"]
    assert [task["task_id"] for task in dashboard["tasks"]] == ["task-newer", "task-older"]
    assert listed[0]["latest_processed_at"] == "2026-04-01T00:02:00.000000Z"


def test_postgres_repository_uses_exact_task_id_matching():
    task_id = "task-c40416e1314a432e89e58a531af26496"
    artifacts = [
        ("artifact-1", "task_prompt", {"prompt": "Google profile", "locale": "en"}),
        (
            "artifact-2",
            "task_interpretation",
            {
                "resolved_subject": "Google",
                "family": "organization",
            },
        ),
        ("artifact-3", "task_run", {"status": "success", "reason": "complete"}),
    ]
    summary_rows = [
        (task_id, "Google profile", "Google", "organization", "success", "complete", "2026-04-01 12:00:00+00"),
    ]

    repository = PostgresTaskRepository(
        connection_factory=lambda: _StubConnection(task_id, artifacts, summary_rows)
    )

    assert repository.list_tasks()[0]["task_id"] == task_id
    assert repository.get_task(task_id)["prompt"] == "Google profile"
    try:
        repository.get_task("task-c40416e1314a432e89e58a531af2")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected KeyError for non-exact task_id")


def test_postgres_repository_lists_most_recent_tasks_first():
    summary_rows = [
        ("task-newer", "Newer profile", "Google", "organization", "success", "complete", "2026-04-01 12:00:00+00"),
        ("task-older", "Older profile", "ASPI", "organization", "partial", "reextract_required", "2026-03-31 12:00:00+00"),
    ]
    repository = PostgresTaskRepository(
        connection_factory=lambda: _StubConnection("task-newer", [], summary_rows)
    )

    assert [task["task_id"] for task in repository.list_tasks()] == ["task-newer", "task-older"]


def test_postgres_repository_uses_default_dsn():
    repository = PostgresTaskRepository(connection_factory=lambda: _StubConnection("", [], []))
    assert repository.dsn == DEFAULT_POSTGRES_DSN


def test_generated_ids_are_prefixed_and_unique():
    from tracerelay.evolution.ids import next_id

    ids = {next_id("task") for _ in range(64)}
    assert len(ids) == 64
    assert all(identifier.startswith("task-") for identifier in ids)
