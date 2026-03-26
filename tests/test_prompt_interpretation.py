import pytest

from schemaledger.models import TaskSpec
from schemaledger.prompt_interpretation import PromptInterpreter


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
