from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .evolution.ids import next_id
from .models import ArtifactRecord, SchemaVersion


class ArtifactSchemaStore:
    def __init__(self, artifact_store: Any) -> None:
        self.artifact_store = artifact_store

    def latest_for_family(self, family: str) -> SchemaVersion | None:
        schemas = [schema for schema in self.all_schemas() if schema.family == family]
        if not schemas:
            return None
        return max(schemas, key=lambda item: item.version)

    def all_schemas(self) -> tuple[SchemaVersion, ...]:
        artifacts = getattr(self.artifact_store, "all_artifacts")()
        schemas: list[SchemaVersion] = []
        for artifact in artifacts:
            if artifact.artifact_type != "schema_version":
                continue
            schemas.append(self._schema_from_payload(artifact.payload))
        return tuple(schemas)

    def create_or_update_schema(
        self,
        task_id: str,
        family: str,
        payload: dict[str, object],
        parent: SchemaVersion | None,
    ) -> SchemaVersion:
        required_fields, optional_fields, relations = _normalize_schema_keys(
            payload.get("required_fields", []),
            payload.get("optional_fields", []),
            payload.get("relations", []),
        )
        schema = SchemaVersion(
            schema_id=next_id("schema"),
            family=family,
            version=1 if parent is None else parent.version + 1,
            parent_schema_id=None if parent is None else parent.schema_id,
            required_fields=required_fields,
            optional_fields=optional_fields,
            relations=relations,
            rationale=str(payload.get("rationale", "")),
        )
        self.artifact_store.append(
            ArtifactRecord(
                artifact_id=next_id("artifact"),
                task_id=task_id,
                artifact_type="schema_version",
                payload=asdict(schema),
            )
        )
        return schema

    def record_reference(self, task_id: str, schema: SchemaVersion) -> None:
        self.artifact_store.append(
            ArtifactRecord(
                artifact_id=next_id("artifact"),
                task_id=task_id,
                artifact_type="schema_reference",
                payload=asdict(schema),
            )
        )

    def _schema_from_payload(self, payload: dict[str, object]) -> SchemaVersion:
        required_fields, optional_fields, relations = _normalize_schema_keys(
            payload.get("required_fields", []),
            payload.get("optional_fields", []),
            payload.get("relations", []),
        )
        return SchemaVersion(
            schema_id=str(payload["schema_id"]),
            family=str(payload["family"]),
            version=int(payload["version"]),
            parent_schema_id=str(payload["parent_schema_id"]) if payload.get("parent_schema_id") else None,
            required_fields=required_fields,
            optional_fields=optional_fields,
            relations=relations,
            rationale=str(payload.get("rationale", "")),
        )


def _normalize_schema_keys(
    required_fields: object,
    optional_fields: object,
    relations: object,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    required = _unique_names(required_fields)
    optional = tuple(name for name in _unique_names(optional_fields) if name not in set(required))
    relation_set = set(required) | set(optional)
    relation_values = tuple(name for name in _unique_names(relations) if name not in relation_set)
    return required, optional, relation_values


def _unique_names(values: object) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    if not isinstance(values, (list, tuple)):
        return ()
    for item in values:
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return tuple(result)
