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
        schema = SchemaVersion(
            schema_id=next_id("schema"),
            family=family,
            version=1 if parent is None else parent.version + 1,
            parent_schema_id=None if parent is None else parent.schema_id,
            required_fields=tuple(str(item) for item in payload.get("required_fields", [])),
            optional_fields=tuple(str(item) for item in payload.get("optional_fields", [])),
            relations=tuple(str(item) for item in payload.get("relations", [])),
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
        return SchemaVersion(
            schema_id=str(payload["schema_id"]),
            family=str(payload["family"]),
            version=int(payload["version"]),
            parent_schema_id=str(payload["parent_schema_id"]) if payload.get("parent_schema_id") else None,
            required_fields=tuple(str(item) for item in payload.get("required_fields", [])),
            optional_fields=tuple(str(item) for item in payload.get("optional_fields", [])),
            relations=tuple(str(item) for item in payload.get("relations", [])),
            rationale=str(payload.get("rationale", "")),
        )
