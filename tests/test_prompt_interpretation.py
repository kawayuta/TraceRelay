import pytest

from tracerelay.models import TaskSpec
from tracerelay.prompt_interpretation import PromptInterpreter


@pytest.mark.parametrize(
    ("prompt", "expected_subject", "expected_family"),
    [
        (
            "Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して",
            "Google",
            "organization",
        ),
        (
            "Macrossについて、作品概要だけでなく、主要シリーズ一覧、視聴順、時系列順、主要キャラクター、主要メカ、主要楽曲、制作スタッフを構造化して",
            "Macross",
            "media_work",
        ),
        (
            "日本の少子化対策の政策パッケージを、政策目的、対象人口、実施主体、施策一覧、財源、評価指標、論点で構造化して",
            "日本の少子化対策の政策パッケージ",
            "policy",
        ),
        (
            "このAPI障害について、影響範囲、原因仮説、依存サービス、時系列、再発防止策を構造化して",
            "API障害",
            "system_incident",
        ),
        (
            "TSMCとNVIDIAの関係を、供給関係、製品カテゴリ、依存度、主要リスク、代替可能性で整理して",
            "TSMC と NVIDIA",
            "relationship",
        ),
    ],
)
def test_prompt_interpretation_resolves_subject_and_family(fake_llm, prompt, expected_subject, expected_family):
    interpreter = PromptInterpreter(fake_llm)
    interpretation = interpreter.interpret(TaskSpec(prompt=prompt))
    assert interpretation.resolved_subject == expected_subject
    assert interpretation.family == expected_family


class _ReviewingLLM:
    def interpret_task(self, spec):  # noqa: ANN001
        return {
            "intent": "investigate_subject",
            "resolved_subject": "Macross",
            "subject_candidates": ["Macross"],
            "family": "organization",
            "family_rationale": "The subject is a known entity, so the initial pass stayed generic.",
            "requested_fields": ["series", "viewing_order", "characters", "staff"],
            "requested_relations": [],
            "scope_hints": ["series", "viewing_order", "characters", "staff"],
            "task_shape": "subject_analysis",
            "locale": "ja",
        }

    def review_task_interpretation(self, spec, interpretation):  # noqa: ANN001
        return {
            "family": "media_work",
            "family_rationale": "The requested fields describe a title, its viewing order, characters, and staff.",
        }


def test_prompt_interpretation_rechecks_family_with_review_layer():
    interpreter = PromptInterpreter(_ReviewingLLM())
    interpretation = interpreter.interpret(TaskSpec(prompt="Macrossの視聴順と主要キャラと制作スタッフを整理して"))

    assert interpretation.family == "media_work"
    assert interpretation.initial_family == "organization"
    assert interpretation.family_review_rationale
