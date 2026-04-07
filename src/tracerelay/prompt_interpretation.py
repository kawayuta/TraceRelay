from __future__ import annotations

from dataclasses import replace

from .llm import LLMError, StructuredLLM
from .models import SubjectParticipant, TaskInterpretation, TaskSpec


class PromptInterpreter:
    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    def interpret(self, spec: TaskSpec) -> TaskInterpretation:
        payload = self.llm.interpret_task(spec)
        interpretation = replace(_interpret_from_llm(payload), memory_context=dict(spec.memory_context))
        reviewer = getattr(self.llm, "review_task_interpretation", None)
        if not callable(reviewer):
            return interpretation
        try:
            review_payload = reviewer(spec, interpretation)
            return _apply_family_review(interpretation, review_payload)
        except LLMError:
            return interpretation


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
    subject_aliases = tuple(str(item) for item in payload.get("subject_aliases", []) if str(item).strip())
    participants = tuple(_participant_from_payload(item) for item in payload.get("subject_participants", []))
    return TaskInterpretation(
        intent=str(payload["intent"]),
        resolved_subject=str(payload["resolved_subject"]),
        subject_candidates=tuple(str(item) for item in subject_candidates),
        subject_aliases=subject_aliases,
        subject_topology=str(payload.get("subject_topology", "atomic")),
        branch_strategy=str(payload.get("branch_strategy", "none")),
        scope_key=str(payload.get("scope_key", "")),
        subject_participants=participants,
        family=str(payload["family"]),
        family_rationale=str(payload.get("family_rationale", "")),
        requested_fields=requested_fields,
        requested_relations=requested_relations,
        scope_hints=tuple(str(item) for item in scope_hints),
        task_shape=str(payload.get("task_shape", "subject_analysis")),
        locale=str(payload.get("locale", "auto")),
    )


def _participant_from_payload(payload: object) -> SubjectParticipant:
    data = dict(payload) if isinstance(payload, dict) else {}
    aliases = tuple(str(item) for item in data.get("aliases", []) if str(item).strip())
    return SubjectParticipant(
        subject=str(data.get("subject", "")),
        subject_key=str(data.get("subject_key", "")),
        role=str(data.get("role", "participant")),
        aliases=aliases,
        family_hint=str(data.get("family_hint", "")),
        confidence=float(data.get("confidence", 1.0)),
        spawn=bool(data.get("spawn", True)),
    )


def _apply_family_review(
    interpretation: TaskInterpretation,
    payload: dict[str, object],
) -> TaskInterpretation:
    family = str(payload.get("family", "")).strip()
    if not family:
        raise LLMError("Task interpretation family review is missing family")
    rationale = str(payload.get("family_rationale", "")).strip() or interpretation.family_rationale
    if family == interpretation.family:
        return replace(
            interpretation,
            family_rationale=rationale,
            family_review_rationale=rationale,
        )
    return replace(
        interpretation,
        family=family,
        initial_family=interpretation.family,
        family_rationale=rationale,
        family_review_rationale=rationale,
    )
