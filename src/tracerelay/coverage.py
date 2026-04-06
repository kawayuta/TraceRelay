from __future__ import annotations

from .models import CoverageReport, ExtractionResult, SchemaVersion, TaskInterpretation


class CoverageEvaluator:
    def evaluate(
        self,
        schema: SchemaVersion,
        interpretation: TaskInterpretation,
        extraction: ExtractionResult,
    ) -> CoverageReport:
        payload = extraction.payload
        deprecated_fields = set(schema.deprecated_fields)
        deprecated_relations = set(schema.deprecated_relations)
        active_required = tuple(field for field in schema.required_fields if field not in deprecated_fields)
        active_optional = tuple(field for field in schema.optional_fields if field not in deprecated_fields)
        active_relations = tuple(relation for relation in schema.relations if relation not in deprecated_relations)
        supported_fields = set(active_required + active_optional)
        supported_relations = set(active_relations)
        supported_keys = supported_fields | supported_relations
        requested_fields = set(interpretation.requested_fields)
        requested_relations = set(interpretation.requested_relations)

        missing_fields = tuple(sorted(requested_fields - supported_keys))
        missing_relations = tuple(sorted(requested_relations - supported_keys))

        missing_values: list[str] = []
        for field_name in sorted(set(active_required) | (requested_fields & supported_keys)):
            if not _has_value(payload.get(field_name)):
                missing_values.append(field_name)
        for relation_name in sorted(requested_relations & set(active_relations)):
            if not _has_value(payload.get(relation_name)):
                missing_values.append(relation_name)

        dominant_issue = "none"
        if missing_fields or missing_relations:
            dominant_issue = "schema"
        elif missing_values:
            dominant_issue = "values"
        return CoverageReport(
            missing_values=tuple(missing_values),
            missing_fields=missing_fields,
            missing_relations=missing_relations,
            dominant_issue=dominant_issue,
        )


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True
