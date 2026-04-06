from __future__ import annotations

from .evolution.ids import next_id
from .models import ReviewDecision, SchemaCandidate, SchemaVersion, TaskEvent


def plan_schema_patch(candidate: SchemaCandidate, applied_schema: SchemaVersion) -> tuple[ReviewDecision, TaskEvent]:
    changes: list[str] = []
    if candidate.additive_fields:
        changes.append(f"fields: {', '.join(candidate.additive_fields)}")
    if candidate.additive_relations:
        changes.append(f"relations: {', '.join(candidate.additive_relations)}")
    if candidate.deprecated_fields:
        changes.append(f"deprecated fields: {', '.join(candidate.deprecated_fields)}")
    if candidate.deprecated_relations:
        changes.append(f"deprecated relations: {', '.join(candidate.deprecated_relations)}")
    if candidate.pruning_hints:
        changes.append(f"pruning hints: {', '.join(candidate.pruning_hints)}")
    review = ReviewDecision(
        review_id=next_id("review"),
        candidate_id=candidate.candidate_id,
        disposition="auto_applied",
        notes=(
            "LLM generated a schema update and the runtime applied it automatically."
            if not changes
            else "LLM generated a schema update and the runtime applied it automatically: " + "; ".join(changes)
        ),
    )
    event = TaskEvent(
        event_id=next_id("event"),
        kind="schema_version_applied",
        details={
            "candidate_id": candidate.candidate_id,
            "family": candidate.family,
            "schema_id": applied_schema.schema_id,
            "version": applied_schema.version,
            "fields": list(candidate.additive_fields),
            "relations": list(candidate.additive_relations),
            "deprecated_fields": list(candidate.deprecated_fields),
            "deprecated_relations": list(candidate.deprecated_relations),
            "pruning_hints": list(candidate.pruning_hints),
        },
    )
    return review, event
