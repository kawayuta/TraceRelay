from __future__ import annotations

import re
from dataclasses import replace

from .memory import normalize_subject
from .models import SubjectParticipant, TaskInterpretation, TaskSpec


_COMPOSITE_TASK_SHAPES = {
    "comparison",
    "comparative_analysis",
    "relationship",
    "multi_subject_analysis",
    "pair_analysis",
}

_COMPOSITE_FAMILIES = {
    "relationship",
    "supply_chain_relation",
}


def enrich_interpretation_subject_graph(
    interpretation: TaskInterpretation,
    spec: TaskSpec,
) -> TaskInterpretation:
    forced_subject = str(spec.execution_context.get("forced_subject") or spec.branch_subject or "").strip()
    if forced_subject:
        return _forced_atomic_interpretation(interpretation, spec, forced_subject)

    normalized_resolved = normalize_subject(interpretation.resolved_subject)
    payload_aliases = [str(item).strip() for item in interpretation.subject_aliases if str(item).strip()]
    payload_participants = tuple(_normalize_participant(participant) for participant in interpretation.subject_participants)
    payload_participants = tuple(participant for participant in payload_participants if participant.subject_key != "unknown")

    if payload_participants:
        participants = _dedupe_participants(payload_participants)
        topology = str(interpretation.subject_topology or _infer_topology_from_participants(participants)).strip() or "composite"
        branch_strategy = (
            str(interpretation.branch_strategy or "").strip()
            or ("spawn_atomic_subjects" if len(participants) > 1 else "none")
        )
        aliases = _dedupe_strings(payload_aliases + list(_semantic_aliases_from_candidates(interpretation, participants)))
        scope_key = str(interpretation.scope_key or normalized_resolved or participants[0].subject_key)
        return replace(
            interpretation,
            resolved_subject=interpretation.resolved_subject,
            subject_aliases=tuple(aliases),
            subject_topology=topology,
            branch_strategy=branch_strategy,
            scope_key=scope_key,
            subject_participants=participants,
        )

    if _should_spawn_composite_branches(interpretation):
        participants = _participants_from_candidates(interpretation)
        if len(participants) >= 2:
            aliases = _dedupe_strings(payload_aliases + list(_semantic_aliases_from_candidates(interpretation, participants)))
            return replace(
                interpretation,
                subject_aliases=tuple(aliases),
                subject_topology="composite",
                branch_strategy="spawn_atomic_subjects",
                scope_key=str(interpretation.scope_key or normalized_resolved),
                subject_participants=participants,
            )

    aliases = _dedupe_strings(payload_aliases + [item for item in interpretation.subject_candidates if item != interpretation.resolved_subject])
    return replace(
        interpretation,
        subject_aliases=tuple(aliases),
        subject_topology=str(interpretation.subject_topology or "atomic"),
        branch_strategy=str(interpretation.branch_strategy or "none"),
        scope_key=str(interpretation.scope_key or normalized_resolved),
        subject_participants=(
            SubjectParticipant(
                subject=interpretation.resolved_subject,
                subject_key=normalized_resolved,
                aliases=tuple(aliases),
                role="subject",
                family_hint=interpretation.family,
                confidence=1.0,
                spawn=False,
            ),
        ),
    )


def subject_graph_payload(interpretation: TaskInterpretation) -> dict[str, object]:
    return {
        "resolved_subject": interpretation.resolved_subject,
        "scope_key": interpretation.scope_key or normalize_subject(interpretation.resolved_subject),
        "subject_topology": interpretation.subject_topology or "atomic",
        "branch_strategy": interpretation.branch_strategy or "none",
        "subject_aliases": list(interpretation.subject_aliases),
        "participants": [
            {
                "subject": participant.subject,
                "subject_key": participant.subject_key,
                "role": participant.role,
                "aliases": list(participant.aliases),
                "family_hint": participant.family_hint,
                "confidence": participant.confidence,
                "spawn": participant.spawn,
            }
            for participant in interpretation.subject_participants
        ],
    }


def search_aliases_for_interpretation(interpretation: TaskInterpretation) -> tuple[str, ...]:
    aliases: list[str] = []
    aliases.extend(str(item) for item in interpretation.subject_aliases)
    aliases.extend(str(item) for item in interpretation.subject_candidates if str(item).strip())
    aliases.append(interpretation.resolved_subject)
    for participant in interpretation.subject_participants:
        aliases.append(participant.subject)
        aliases.extend(participant.aliases)
    return tuple(_dedupe_strings(aliases))


def participant_subject_keys(interpretation: TaskInterpretation) -> tuple[str, ...]:
    return tuple(
        participant.subject_key
        for participant in interpretation.subject_participants
        if participant.subject_key and participant.subject_key != "unknown"
    )


def subject_graph_is_composite(interpretation: TaskInterpretation) -> bool:
    return (
        str(interpretation.subject_topology or "atomic") != "atomic"
        and len(participant_subject_keys(interpretation)) > 1
    )


def _forced_atomic_interpretation(
    interpretation: TaskInterpretation,
    spec: TaskSpec,
    forced_subject: str,
) -> TaskInterpretation:
    normalized = normalize_subject(forced_subject)
    sibling_subjects = [
        str(item).strip()
        for item in spec.execution_context.get("counterpart_subjects", [])
        if str(item).strip() and str(item).strip() != forced_subject
    ]
    aliases = _dedupe_strings(
        [forced_subject]
        + [str(item) for item in interpretation.subject_aliases]
        + [str(item) for item in interpretation.subject_candidates if str(item).strip() and str(item).strip() != forced_subject]
    )
    branch_family_hint = str(spec.execution_context.get("preferred_atomic_family") or "").strip()
    if branch_family_hint:
        family = branch_family_hint
    else:
        family = interpretation.family
    return replace(
        interpretation,
        resolved_subject=forced_subject,
        subject_candidates=(forced_subject,),
        subject_aliases=tuple(aliases),
        subject_topology="atomic",
        branch_strategy="none",
        scope_key=normalized,
        family=family,
        subject_participants=(
            SubjectParticipant(
                subject=forced_subject,
                subject_key=normalized,
                role=str(spec.branch_role or "branch_subject"),
                aliases=tuple(alias for alias in aliases if alias != forced_subject),
                family_hint=family,
                confidence=1.0,
                spawn=False,
            ),
        ),
        branch_context={
            **dict(interpretation.branch_context),
            "branch_mode": "atomic_subject",
            "parent_task_id": spec.parent_task_id or "",
            "root_task_id": spec.root_task_id or spec.parent_task_id or "",
            "counterpart_subjects": sibling_subjects,
        },
    )


def _participants_from_candidates(interpretation: TaskInterpretation) -> tuple[SubjectParticipant, ...]:
    participants: list[SubjectParticipant] = []
    for subject in interpretation.subject_candidates:
        cleaned = str(subject).strip()
        if not cleaned or cleaned == interpretation.resolved_subject:
            continue
        normalized = normalize_subject(cleaned)
        if normalized == "unknown":
            continue
        participants.append(
            SubjectParticipant(
                subject=cleaned,
                subject_key=normalized,
                role="participant",
                aliases=(),
                family_hint="organization",
                confidence=0.85,
                spawn=True,
            )
        )
    if participants:
        return _dedupe_participants(tuple(participants))
    for token in _split_composite_subject_text(interpretation.resolved_subject):
        participants.append(
            SubjectParticipant(
                subject=token,
                subject_key=normalize_subject(token),
                role="participant",
                aliases=(),
                family_hint="organization",
                confidence=0.65,
                spawn=True,
            )
        )
    return _dedupe_participants(tuple(participants))


def _semantic_aliases_from_candidates(
    interpretation: TaskInterpretation,
    participants: tuple[SubjectParticipant, ...],
) -> tuple[str, ...]:
    participant_keys = {participant.subject_key for participant in participants}
    aliases: list[str] = []
    for subject in interpretation.subject_candidates:
        cleaned = str(subject).strip()
        if not cleaned or cleaned == interpretation.resolved_subject:
            continue
        if normalize_subject(cleaned) in participant_keys:
            continue
        aliases.append(cleaned)
    return tuple(_dedupe_strings(aliases))


def _normalize_participant(participant: SubjectParticipant) -> SubjectParticipant:
    normalized_key = normalize_subject(participant.subject)
    aliases = tuple(_dedupe_strings(participant.aliases))
    return replace(
        participant,
        subject=participant.subject.strip(),
        subject_key=normalized_key if normalized_key != "unknown" else participant.subject_key,
        aliases=aliases,
    )


def _dedupe_participants(participants: tuple[SubjectParticipant, ...]) -> tuple[SubjectParticipant, ...]:
    seen: set[str] = set()
    result: list[SubjectParticipant] = []
    for participant in participants:
        key = participant.subject_key or normalize_subject(participant.subject)
        if not key or key == "unknown" or key in seen:
            continue
        seen.add(key)
        result.append(replace(participant, subject_key=key))
    return tuple(result)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        if not cleaned:
            continue
        marker = cleaned.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(cleaned)
    return result


def _should_spawn_composite_branches(interpretation: TaskInterpretation) -> bool:
    candidate_keys = {
        normalize_subject(subject)
        for subject in interpretation.subject_candidates
        if str(subject).strip()
    }
    candidate_keys.discard(normalize_subject(interpretation.resolved_subject))
    if interpretation.family in _COMPOSITE_FAMILIES:
        return len(candidate_keys) >= 2
    if interpretation.task_shape in _COMPOSITE_TASK_SHAPES:
        return len(candidate_keys) >= 2
    return False


def _infer_topology_from_participants(participants: tuple[SubjectParticipant, ...]) -> str:
    if len(participants) <= 1:
        return "atomic"
    if len(participants) == 2:
        return "pair"
    return "set"


def _split_composite_subject_text(text: str) -> tuple[str, ...]:
    parts = [
        " ".join(part.split()).strip()
        for part in re.split(r"\s*(?:/|,|&|\+|\||、|・|と)\s*", text)
    ]
    return tuple(part for part in parts if part)
