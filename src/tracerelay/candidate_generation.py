from __future__ import annotations

from .evolution.ids import next_id
from .models import SchemaCandidate, SchemaRequirement, SchemaVersion


def build_candidate(
    requirement: SchemaRequirement,
    current_schema: SchemaVersion,
    proposed_schema: SchemaVersion,
) -> SchemaCandidate:
    current_fields = set(current_schema.required_fields + current_schema.optional_fields)
    proposed_fields = set(proposed_schema.required_fields + proposed_schema.optional_fields)
    return SchemaCandidate(
        candidate_id=next_id("cand"),
        requirement_id=requirement.requirement_id,
        family=requirement.family,
        additive_fields=tuple(sorted(proposed_fields - current_fields)),
        additive_relations=tuple(sorted(set(proposed_schema.relations) - set(current_schema.relations))),
        deprecated_fields=tuple(
            sorted(set(proposed_schema.deprecated_fields) - set(current_schema.deprecated_fields))
        ),
        deprecated_relations=tuple(
            sorted(set(proposed_schema.deprecated_relations) - set(current_schema.deprecated_relations))
        ),
        pruning_hints=tuple(
            sorted(set(proposed_schema.pruning_hints) - set(current_schema.pruning_hints))
        ),
        rationale=proposed_schema.rationale,
    )
