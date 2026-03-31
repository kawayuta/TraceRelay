from __future__ import annotations

import json
import os
from unittest.mock import patch

from schemaledger.embeddings import (
    EmbeddingError,
    GeminiEmbeddingConfig,
    GeminiTextEmbedder,
    LMStudioTextEmbedder,
    LMStudioEmbeddingConfig,
    OpenAIEmbeddingConfig,
    OpenAITextEmbedder,
    OllamaEmbeddingConfig,
    OllamaTextEmbedder,
    clear_embedding_caches,
    embedder_from_env,
)
from schemaledger.extraction import Extractor
from schemaledger.memory import ArtifactMemoryStore, normalize_subject
from schemaledger.models import ExtractionResult, TaskSpec
from schemaledger.task_flow import InMemoryArtifactStore
from schemaledger.task_runtime import TaskRuntime


class RecordingMemoryLLM:
    def __init__(self) -> None:
        self.interpret_contexts: list[dict[str, object]] = []
        self.schema_contexts: list[dict[str, object]] = []
        self.extract_contexts: list[dict[str, object]] = []

    def interpret_task(self, spec: TaskSpec) -> dict[str, object]:
        self.interpret_contexts.append(dict(spec.memory_context))
        if "ASPI" in spec.prompt:
            return {
                "intent": "investigate_subject",
                "resolved_subject": "ASPI Helium Project",
                "subject_candidates": ["ASPI Helium Project", "ASPI"],
                "family": "deep_research_target",
                "family_rationale": "The user is iterating on an ASPI research target.",
                "requested_fields": ["overview", "market_cap", "major_risks"],
                "requested_relations": ["financing_sources"],
                "scope_hints": ["overview", "market_cap", "major_risks", "financing_sources"],
                "task_shape": "subject_analysis",
                "locale": "ja",
            }
        return {
            "intent": "investigate_subject",
            "resolved_subject": "Google",
            "subject_candidates": ["Google"],
            "family": "organization",
            "family_rationale": "The task asks for a company profile.",
            "requested_fields": ["overview", "business_lines"],
            "requested_relations": ["subsidiaries"],
            "scope_hints": ["overview", "business_lines", "subsidiaries"],
            "task_shape": "subject_analysis",
            "locale": "ja",
        }

    def build_initial_schema(self, interpretation):  # noqa: ANN001
        self.schema_contexts.append(dict(interpretation.memory_context))
        return {
            "family": interpretation.family,
            "required_fields": list(interpretation.requested_fields),
            "optional_fields": [],
            "relations": list(interpretation.requested_relations),
            "rationale": "Use the requested task surface.",
        }

    def evolve_schema(self, interpretation, schema, coverage, extraction):  # noqa: ANN001
        return {
            "family": interpretation.family,
            "required_fields": list(schema.required_fields),
            "optional_fields": list(schema.optional_fields),
            "relations": list(schema.relations),
            "rationale": "No-op",
        }

    def extract_task(self, family, interpretation, schema, attempt):  # noqa: ANN001
        self.extract_contexts.append(dict(interpretation.memory_context))
        payload: dict[str, object] = {}
        for field_name in schema.required_fields + schema.optional_fields:
            if field_name == "market_cap":
                payload[field_name] = "513.74M USD"
            elif field_name == "major_risks":
                payload[field_name] = ["execution_risk", "commodity_price_risk"]
            else:
                payload[field_name] = f"{interpretation.resolved_subject}:{field_name}"
        for relation_name in schema.relations:
            payload[relation_name] = [f"{interpretation.resolved_subject}:{relation_name}"]
        return ExtractionResult(
            payload=payload,
            status="success",
            provider_metadata={"provider": "recording-memory-llm", "attempt": attempt},
        )


class _FakeEmbeddingResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_FakeEmbeddingResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_memory_learning_and_subject_retrieval_loop():
    store = InMemoryArtifactStore()
    llm = RecordingMemoryLLM()
    runtime = TaskRuntime(llm=llm, artifact_store=store)

    first = runtime.run_task(TaskSpec(prompt="ASPIの概要を構造化して", user_id="alice"))
    second = runtime.run_task(
        TaskSpec(
            prompt="ASPIについて前回学んだことも踏まえて、時価総額と主要リスクを深掘りして",
            user_id="alice",
        )
    )

    assert first.status == "success"
    assert second.status == "success"
    assert second.memory_context is not None
    assert second.memory_context.profile is not None
    assert second.memory_context.profile.user_id == "alice"
    assert second.memory_context.prompt_hits
    assert second.memory_context.subject_hits
    assert any("ASPI Helium Project" in hit.text for hit in second.memory_context.subject_hits)
    assert "subject_memory_1" in second.memory_context.context_text

    task_artifacts = store.list_for_task(second.task_id)
    assert any(artifact.artifact_type == "task_memory_context" for artifact in task_artifacts)
    assert sum(artifact.artifact_type == "memory_document" for artifact in store.all_artifacts()) >= 4
    assert any(artifact.artifact_type == "user_profile" for artifact in store.all_artifacts())

    assert llm.interpret_contexts[1]["prompt_hits"]
    assert llm.extract_contexts[1]["subject_hits"]


def test_memory_store_search_and_profile_snapshot():
    store = InMemoryArtifactStore()
    llm = RecordingMemoryLLM()
    runtime = TaskRuntime(llm=llm, artifact_store=store)

    runtime.run_task(TaskSpec(prompt="Googleの事業内容を構造化して", user_id="analyst"))
    runtime.run_task(TaskSpec(prompt="ASPIの概要を構造化して", user_id="analyst"))

    memory_store = ArtifactMemoryStore(store)
    profile = memory_store.latest_user_profile("analyst")
    assert profile is not None
    assert profile.user_id == "analyst"
    assert "organization" in profile.family_preferences or "deep_research_target" in profile.family_preferences

    hits = memory_store.search(
        "ASPI Helium Project market cap risks",
        user_id="analyst",
        subject_key=normalize_subject("ASPI Helium Project"),
        top_k=3,
    )
    assert hits
    assert hits[0].subject_key == normalize_subject("ASPI Helium Project")


def test_lmstudio_text_embedder_calls_embeddings_endpoint():
    client = LMStudioTextEmbedder(
        LMStudioEmbeddingConfig(
            base_url="http://127.0.0.1:1234",
            model="text-embedding-nomic-embed-text-v1.5",
        )
    )

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "text-embedding-nomic-embed-text-v1.5"
        assert payload["input"] == "Google memory query"
        return _FakeEmbeddingResponse(
            {
                "data": [
                    {
                        "embedding": [0.1, 0.2, 0.3],
                    }
                ]
            }
        )

    with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
        vector = client.embed("Google memory query")

    assert vector == (0.1, 0.2, 0.3)


def test_embedder_from_env_auto_detects_lmstudio_embedding_model():
    clear_embedding_caches()

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        if req.full_url.endswith("/v1/models"):
            return _FakeEmbeddingResponse(
                {
                    "data": [
                        {"id": "qwen-chat-model"},
                        {"id": "text-embedding-nomic-embed-text-v1.5"},
                    ]
                }
            )
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "text-embedding-nomic-embed-text-v1.5"
        return _FakeEmbeddingResponse({"data": [{"embedding": [0.4, 0.5]}]})

    with patch.dict(
        os.environ,
        {
            "SCHEMALEDGER_LM_STUDIO_BASE_URL": "http://127.0.0.1:1234",
        },
        clear=False,
    ):
        with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
            embedder = embedder_from_env()
            vector = embedder.embed("ASPI")

    assert getattr(embedder, "algorithm", "") == "lmstudio_embeddings_v1"
    assert vector == (0.4, 0.5)


def test_ollama_text_embedder_calls_embeddings_endpoint():
    client = OllamaTextEmbedder(
        OllamaEmbeddingConfig(
            base_url="http://127.0.0.1:11434",
            model="nomic-embed-text",
        )
    )

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        assert req.full_url.endswith("/api/embed")
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "nomic-embed-text"
        assert payload["input"] == "Google memory query"
        return _FakeEmbeddingResponse({"embeddings": [[0.9, 0.8, 0.7]]})

    with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
        vector = client.embed("Google memory query")

    assert vector == (0.9, 0.8, 0.7)


def test_embedder_from_env_auto_detects_ollama_embedding_model():
    clear_embedding_caches()

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        if req.full_url.endswith("/api/tags"):
            return _FakeEmbeddingResponse(
                {
                    "models": [
                        {"name": "qwen3:latest"},
                        {"name": "nomic-embed-text:latest"},
                    ]
                }
            )
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "nomic-embed-text:latest"
        return _FakeEmbeddingResponse({"embeddings": [[0.6, 0.5]]})

    with patch.dict(
        os.environ,
        {
            "SCHEMALEDGER_EMBEDDING_PROVIDER": "ollama",
            "SCHEMALEDGER_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        },
        clear=True,
    ):
        with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
            embedder = embedder_from_env()
            vector = embedder.embed("ASPI")

    assert getattr(embedder, "algorithm", "") == "ollama_embeddings_v1"
    assert vector == (0.6, 0.5)


def test_openai_text_embedder_calls_embeddings_endpoint():
    client = OpenAITextEmbedder(
        OpenAIEmbeddingConfig(
            api_key="sk-test",
            model="text-embedding-3-small",
        )
    )

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        assert req.full_url.endswith("/v1/embeddings")
        assert req.headers["Authorization"] == "Bearer sk-test"
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "text-embedding-3-small"
        assert payload["input"] == "Google memory query"
        return _FakeEmbeddingResponse({"data": [{"embedding": [0.11, 0.22, 0.33]}]})

    with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
        vector = client.embed("Google memory query")

    assert vector == (0.11, 0.22, 0.33)


def test_embedder_from_env_selects_openai():
    clear_embedding_caches()

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "text-embedding-3-small"
        return _FakeEmbeddingResponse({"data": [{"embedding": [0.12, 0.34]}]})

    with patch.dict(
        os.environ,
        {
            "SCHEMALEDGER_EMBEDDING_PROVIDER": "openai",
            "SCHEMALEDGER_OPENAI_API_KEY": "sk-test",
            "SCHEMALEDGER_OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
        },
        clear=True,
    ):
        with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
            embedder = embedder_from_env()
            vector = embedder.embed("ASPI")

    assert getattr(embedder, "algorithm", "") == "openai_embeddings_v1"
    assert vector == (0.12, 0.34)


def test_gemini_text_embedder_calls_embeddings_endpoint():
    client = GeminiTextEmbedder(
        GeminiEmbeddingConfig(
            api_key="gem-key",
            model="gemini-embedding-001",
        )
    )

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        assert "/v1beta/models/gemini-embedding-001:embedContent" in req.full_url
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "models/gemini-embedding-001"
        assert payload["content"]["parts"][0]["text"] == "Google memory query"
        return _FakeEmbeddingResponse({"embedding": {"values": [0.21, 0.31, 0.41]}})

    with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
        vector = client.embed("Google memory query")

    assert vector == (0.21, 0.31, 0.41)


def test_embedder_from_env_selects_gemini():
    clear_embedding_caches()

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "models/gemini-embedding-001"
        return _FakeEmbeddingResponse({"embedding": {"values": [0.56, 0.78]}})

    with patch.dict(
        os.environ,
        {
            "SCHEMALEDGER_EMBEDDING_PROVIDER": "gemini",
            "SCHEMALEDGER_GEMINI_API_KEY": "gem-key",
            "SCHEMALEDGER_GEMINI_EMBEDDING_MODEL": "gemini-embedding-001",
        },
        clear=True,
    ):
        with patch("schemaledger.embeddings.request.urlopen", fake_urlopen):
            embedder = embedder_from_env()
            vector = embedder.embed("ASPI")

    assert getattr(embedder, "algorithm", "") == "gemini_embeddings_v1"
    assert vector == (0.56, 0.78)


def test_embedder_from_env_rejects_claude_embedding_provider():
    clear_embedding_caches()

    with patch.dict(
        os.environ,
        {
            "SCHEMALEDGER_EMBEDDING_PROVIDER": "claude",
        },
        clear=True,
    ):
        try:
            embedder_from_env()
        except EmbeddingError as exc:
            assert "does not currently expose a direct embeddings API" in str(exc)
        else:
            raise AssertionError("Expected claude embedding provider to raise EmbeddingError")
