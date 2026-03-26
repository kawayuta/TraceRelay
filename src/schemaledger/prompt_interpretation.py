from __future__ import annotations

from .llm import LLMError, StructuredLLM
from .models import TaskInterpretation, TaskSpec


class PromptInterpreter:
    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    def interpret(self, spec: TaskSpec) -> TaskInterpretation:
        payload = self.llm.interpret_task(spec)
        return _interpret_from_llm(payload)


def _interpret_from_llm(payload: dict[str, object]) -> TaskInterpretation:
    required = ["intent", "resolved_subject", "family", "requested_fields", "requested_relations"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise LLMError(f"Task interpretation is missing required keys: {', '.join(missing)}")
    requested_fields = tuple(str(item) for item in payload.get("requested_fields", []))
    requested_relations = tuple(str(item) for item in payload.get("requested_relations", []))
    scope_hints = payload.get("scope_hints")
    if scope_hints is None:
        scope_hints = list(requested_fields + requested_relations)
    subject_candidates = payload.get("subject_candidates") or [payload["resolved_subject"]]
    return TaskInterpretation(
        intent=str(payload["intent"]),
        resolved_subject=str(payload["resolved_subject"]),
        subject_candidates=tuple(str(item) for item in subject_candidates),
        family=str(payload["family"]),
        family_rationale=str(payload.get("family_rationale", "")),
        requested_fields=requested_fields,
        requested_relations=requested_relations,
        scope_hints=tuple(str(item) for item in scope_hints),
        task_shape=str(payload.get("task_shape", "subject_analysis")),
        locale=str(payload.get("locale", "auto")),
    )
