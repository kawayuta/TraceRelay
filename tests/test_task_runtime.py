import pytest

from tracerelay.memory import normalize_subject
from tracerelay.mcp.server import LocalMCPServer
from tracerelay.models import TaskSpec
from tracerelay.task_flow import JsonlArtifactStore
from tracerelay.web.repository import TaskRepository
from tracerelay.task_runtime import TaskRuntime


def test_runtime_requires_llm():
    with pytest.raises(RuntimeError):
        TaskRuntime(llm=None)


def test_media_prompt_reextracts_with_same_schema(fake_llm):
    runtime = TaskRuntime(llm=fake_llm)
    run = runtime.run_task(
        TaskSpec(
            prompt="Macrossについて、作品概要だけでなく、主要シリーズ一覧、視聴順、時系列順、主要キャラクター、主要メカ、主要楽曲、制作スタッフを構造化して"
        )
    )
    assert run.interpretation.family == "media_work"
    assert len(run.extraction_history) == 2
    assert len(run.schema_history) == 1
    assert run.reason == "complete"
    assert run.status == "success"
    assert run.coverage.dominant_issue == "none"
    assert run.evidence_bundle is not None
    assert len(run.evidence_bundle.items) >= 1
    assert [snapshot.chosen_branch_type for snapshot in run.policy_snapshots] == ["reextract", "complete"]


def test_google_prompt_auto_evolves_schema_then_reextracts(fake_llm):
    runtime = TaskRuntime(llm=fake_llm)
    run = runtime.run_task(
        TaskSpec(
            prompt="Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して"
        )
    )
    assert run.interpretation.family == "organization"
    assert run.status == "success"
    assert run.reason == "complete"
    assert len(run.schema_history) == 2
    assert run.schema.version == 2
    assert "regional_presence" in run.schema.optional_fields
    assert "acquisitions" in run.schema.relations
    assert run.gap is not None
    assert run.requirement is not None
    assert run.requirement.gap_id == run.gap.gap_id
    assert run.candidate is not None
    assert "regional_presence" in run.candidate.additive_fields
    assert "acquisitions" in run.candidate.additive_relations
    assert run.review is not None
    assert run.extraction_history[1].provider_metadata["probe_reused"] is True
    assert run.extraction_history[1].provider_metadata["strategy_branch"] == "schema_evolution"
    assert any(event.kind == "schema_version_applied" for event in run.events)
    assert [snapshot.chosen_branch_type for snapshot in run.policy_snapshots] == ["schema_evolution", "complete"]
    assert {artifact.artifact_type for artifact in run.artifacts} >= {
        "task_prompt",
        "task_interpretation",
        "task_evidence_bundle",
        "task_strategy_probe",
        "task_strategy_selection",
        "schema_version",
        "task_extraction",
        "coverage_report",
        "task_branch_decision",
        "schema_gap",
        "schema_requirement",
        "schema_candidate",
        "schema_review",
        "task_event",
        "task_run",
    }


def test_policy_incident_and_relationship_are_llm_selected_and_complete(fake_llm):
    runtime = TaskRuntime(llm=fake_llm)
    prompts = [
        (
            "日本の少子化対策の政策パッケージを、政策目的、対象人口、実施主体、施策一覧、財源、評価指標、論点で構造化して",
            "policy",
        ),
        (
            "このAPI障害について、影響範囲、原因仮説、依存サービス、時系列、再発防止策を構造化して",
            "system_incident",
        ),
        (
            "TSMCとNVIDIAの関係を、供給関係、製品カテゴリ、依存度、主要リスク、代替可能性で整理して",
            "relationship",
        ),
    ]
    for prompt, family in prompts:
        run = runtime.run_task(TaskSpec(prompt=prompt))
        assert run.interpretation.family == family
        assert run.status == "success"
        assert run.reason == "complete"
        assert run.schema.family == family


def test_runtime_scopes_schema_reuse_to_subject(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store)

    google = runtime.run_task(
        TaskSpec(
            prompt="Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して"
        )
    )
    acme = runtime.run_task(TaskSpec(prompt="Please investigate ACME Hypergrid."))

    assert google.schema_history[-1].version == 2
    assert acme.schema_history[0].version == 1
    assert acme.schema_history[0].subject_key == normalize_subject("ACME Hypergrid")
    assert acme.schema_history[0].schema_id != google.schema_history[-1].schema_id


class _SubjectRoutingLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        if "Elon" in spec.prompt:
            return {
                "intent": "investigate_subject",
                "resolved_subject": "Elon Musk",
                "subject_candidates": ["Elon Musk"],
                "family": "organization",
                "family_rationale": "Comparison prompt still routes to an organization-like profile.",
                "requested_fields": ["overview"],
                "requested_relations": [],
                "scope_hints": ["overview"],
                "task_shape": "subject_analysis",
                "locale": "en",
            }
        return {
            "intent": "investigate_subject",
            "resolved_subject": "ASPI",
            "subject_candidates": ["ASPI"],
            "family": "organization",
            "family_rationale": "The task asks for an organization profile.",
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
            "rationale": "Simple schema.",
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
        from tracerelay.models import ExtractionResult

        return ExtractionResult(
            payload={"overview": f"{interpretation.resolved_subject} overview"},
            status="success",
            provider_metadata={"provider": "subject-routing-test", "attempt": attempt},
        )


def test_subject_lookup_prefers_exact_resolved_subject_over_prompt_mentions(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_SubjectRoutingLLM(), artifact_store=store)
    aspi = runtime.run_task(TaskSpec(prompt="ASPIを構造化して整理して"))
    runtime.run_task(TaskSpec(prompt="Elon MuskとASPIの比較メモを整理して"))

    repository = TaskRepository(store)
    server = LocalMCPServer(runtime, store, repository=repository, sync_dsn=None)
    result = server.call_tool("inspect_latest_changes", {"subject": "ASPI"})

    assert result["found"] is True
    assert result["task_id"] == aspi.task_id
    assert result["task"]["interpretation"]["resolved_subject"] == "ASPI"


class _FamilyReviewLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "Macross",
            "subject_candidates": ["Macross"],
            "family": "organization",
            "family_rationale": "The first pass stayed with a generic subject profile.",
            "requested_fields": ["series", "viewing_order", "characters", "staff"],
            "requested_relations": [],
            "scope_hints": ["series", "viewing_order", "characters", "staff"],
            "task_shape": "subject_analysis",
            "locale": "ja",
        }

    def review_task_interpretation(self, spec, interpretation):  # noqa: ANN001
        return {
            "family": "media_work",
            "family_rationale": "The requested schema is centered on a title, viewing order, characters, and staff.",
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
        from tracerelay.models import ExtractionResult

        return ExtractionResult(
            payload={
                "series": ["main series"],
                "viewing_order": ["release order"],
                "characters": ["lead character"],
                "staff": ["key staff"],
            },
            status="success",
            provider_metadata={"provider": "family-review-test", "attempt": attempt},
        )


def test_runtime_rechecks_family_before_schema_selection(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_FamilyReviewLLM(), artifact_store=store)

    run = runtime.run_task(TaskSpec(prompt="Macrossの視聴順と主要キャラと制作スタッフを整理して"))

    assert run.interpretation.family == "media_work"
    assert run.interpretation.initial_family == "organization"
    assert run.schema.family == "media_work"
    assert any(event.kind == "family_revised" for event in run.events)

    repository = TaskRepository(store)
    task = repository.get_task(run.task_id)
    assert task["interpretation"]["family"] == "media_work"
    assert task["interpretation"]["initial_family"] == "organization"


class _FamilyBranchProbeLLM:
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
            "family_rationale": "The subject name looks like a title, so media_work is plausible.",
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
        from tracerelay.models import ExtractionResult

        payload = {"overview": f"{interpretation.resolved_subject} overview"}
        payload["staff"] = [] if family == "media_work" else ["executive staff"]
        return ExtractionResult(
            payload=payload,
            status="success",
            provider_metadata={"provider": "family-branch-probe-test", "attempt": attempt, "family": family},
        )


def test_runtime_can_override_reviewed_family_when_family_probe_prefers_initial(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_FamilyBranchProbeLLM(), artifact_store=store)

    run = runtime.run_task(TaskSpec(prompt="Macrossの概要とスタッフを整理して"))

    assert run.interpretation.family == "organization"
    assert run.interpretation.initial_family == "organization"
    assert run.status == "success"
    assert run.reason == "complete"
    assert any(event.kind == "family_branch_selected" for event in run.events)
    assert {artifact.artifact_type for artifact in run.artifacts} >= {
        "task_family_probe",
        "task_family_selection",
    }

    repository = TaskRepository(store)
    task = repository.get_task(run.task_id)
    assert task["interpretation"]["family"] == "organization"
    assert task["family_selection"]["chosen_family"] == "organization"


class _StrategyPruningLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "ACME Hypergrid",
            "subject_candidates": ["ACME Hypergrid"],
            "family": "organization",
            "family_rationale": "The task asks for an organization profile.",
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
            "rationale": "Add the missing coverage keys and deprecate the noisy legacy slots.",
        }

    def extract_task(self, family, interpretation, schema, attempt):  # noqa: ANN001
        from tracerelay.models import ExtractionResult

        if attempt == 1:
            payload = {
                "overview": "ACME Hypergrid overview",
                "legacy_status": "legacy",
                "old_relation": ["legacy relation"],
            }
        else:
            payload = {
                "overview": "ACME Hypergrid overview",
                "regional_presence": ["US", "JP"],
                "suppliers": ["Supply partner"],
            }
        return ExtractionResult(
            payload=payload,
            status="success",
            provider_metadata={"provider": "strategy-pruning-test", "attempt": attempt},
        )


def test_runtime_prefers_strategy_probe_and_persists_schema_pruning_metadata(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_StrategyPruningLLM(), artifact_store=store)

    run = runtime.run_task(TaskSpec(prompt="Please investigate ACME Hypergrid with regional presence and suppliers."))

    assert run.status == "success"
    assert run.reason == "complete"
    assert len(run.schema_history) == 2
    assert run.policy_snapshots[0].chosen_branch_type == "schema_evolution"
    assert run.extraction_history[1].provider_metadata["probe_reused"] is True
    assert run.extraction_history[1].provider_metadata["strategy_branch"] == "schema_evolution"
    assert run.schema.deprecated_fields == ("legacy_status",)
    assert run.schema.deprecated_relations == ("old_relation",)
    assert run.schema.pruning_hints == ("drop legacy status from future probes",)
    assert run.candidate is not None
    assert run.candidate.deprecated_fields == ("legacy_status",)
    assert run.candidate.deprecated_relations == ("old_relation",)
    assert run.candidate.pruning_hints == ("drop legacy status from future probes",)
    assert run.review is not None
    assert "deprecated fields" in run.review.notes
    assert any(event.details.get("deprecated_fields") == ["legacy_status"] for event in run.events)
    assert {artifact.artifact_type for artifact in run.artifacts} >= {
        "task_strategy_probe",
        "task_strategy_selection",
    }


class _AliasOnlyLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "ASPI Helium Project",
            "subject_candidates": ["ASPI Helium Project", "ASPI"],
            "family": "organization",
            "family_rationale": "This is still a single organization subject with a short alias.",
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
            "rationale": "Simple alias-preserving schema.",
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
        from tracerelay.models import ExtractionResult

        return ExtractionResult(
            payload={"overview": f"{interpretation.resolved_subject} overview"},
            status="success",
            provider_metadata={"provider": "alias-only-test", "attempt": attempt},
        )


def test_relationship_task_materializes_subject_branches_and_graph(fake_llm, tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=fake_llm, artifact_store=store)

    run = runtime.run_task(
        TaskSpec(
            prompt="TSMCとNVIDIAの関係を、供給関係、製品カテゴリ、依存度、主要リスク、代替可能性で整理して"
        )
    )

    assert run.interpretation.family == "relationship"
    assert run.interpretation.subject_topology == "composite"
    assert run.interpretation.branch_strategy == "spawn_atomic_subjects"
    assert run.interpretation.scope_key == normalize_subject("TSMC と NVIDIA")
    assert {participant.subject for participant in run.interpretation.subject_participants} == {"TSMC", "NVIDIA"}
    assert len(run.branch_runs) == 2
    assert {branch.resolved_subject for branch in run.branch_runs} == {"TSMC", "NVIDIA"}
    assert all(branch.family == "organization" for branch in run.branch_runs)
    assert len(run.interpretation.branch_context.get("children", [])) == 2
    assert {artifact.artifact_type for artifact in run.artifacts} >= {
        "task_subject_graph",
        "task_branch_plan",
        "task_branch_bundle",
        "task_relation",
        "subject_relation",
    }

    repository = TaskRepository(store)
    task = repository.get_task(run.task_id)
    assert task["subject_graph"]["subject_topology"] == "composite"
    assert len(task["task_relations"]) == 2
    assert any(relation["relation_type"] == "scope_member" for relation in task["subject_relations"])
    assert any(relation["relation_type"] == "supply_chain_relation" for relation in task["subject_relations"])


def test_alias_candidates_remain_atomic_and_do_not_spawn_subject_branches(tmp_path):
    store = JsonlArtifactStore(tmp_path / "workspace")
    runtime = TaskRuntime(llm=_AliasOnlyLLM(), artifact_store=store)

    run = runtime.run_task(TaskSpec(prompt="ASPIの概要を構造化して整理して"))

    assert run.interpretation.subject_topology == "atomic"
    assert run.interpretation.branch_strategy == "none"
    assert run.branch_runs == ()
    assert run.interpretation.subject_aliases == ("ASPI",)
    assert len(run.interpretation.subject_participants) == 1
    assert run.interpretation.subject_participants[0].subject == "ASPI Helium Project"
    assert not any(artifact.artifact_type == "task_relation" for artifact in run.artifacts)
