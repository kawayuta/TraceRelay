from __future__ import annotations

from .evolution.ids import next_id
from .models import ReviewDecision, SchemaCandidate, SchemaVersion, TaskEvent


def plan_schema_patch(candidate: SchemaCandidate, applied_schema: SchemaVersion) -> tuple[ReviewDecision, TaskEvent]:
    review = ReviewDecision(
        review_id=next_id("review"),
        candidate_id=candidate.candidate_id,
        disposition="auto_applied",
        notes="LLM generated an additive schema update and the runtime applied it automatically.",
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
        },
    )
    return review, event
