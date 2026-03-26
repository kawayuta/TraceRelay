import pytest

from schemaledger.models import TaskSpec
from schemaledger.task_runtime import TaskRuntime


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
    assert any(event.kind == "schema_version_applied" for event in run.events)
    assert {artifact.artifact_type for artifact in run.artifacts} >= {
        "task_prompt",
        "task_interpretation",
        "schema_version",
        "task_extraction",
        "coverage_report",
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
