from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    prompt: str
    locale: str = "auto"
    requested_scope: tuple[str, ...] = ()
    caller: str = "user"


@dataclass(frozen=True)
class TaskInterpretation:
    intent: str
    resolved_subject: str
    subject_candidates: tuple[str, ...]
    family: str
    family_rationale: str
    requested_fields: tuple[str, ...]
    requested_relations: tuple[str, ...]
    scope_hints: tuple[str, ...]
    task_shape: str
    locale: str


@dataclass(frozen=True)
class SchemaVersion:
    schema_id: str
    family: str
    version: int
    parent_schema_id: str | None
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    relations: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class ExtractionResult:
    payload: dict[str, Any]
    status: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoverageReport:
    missing_values: tuple[str, ...]
    missing_fields: tuple[str, ...]
    missing_relations: tuple[str, ...]
    dominant_issue: str


@dataclass(frozen=True)
class SchemaGap:
    gap_id: str
    task_id: str
    family: str
    signals: tuple[str, ...]


@dataclass(frozen=True)
class SchemaRequirement:
    requirement_id: str
    gap_id: str
    family: str
    summary: str


@dataclass(frozen=True)
class SchemaCandidate:
    candidate_id: str
    requirement_id: str
    family: str
    additive_fields: tuple[str, ...]
    additive_relations: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class ReviewDecision:
    review_id: str
    candidate_id: str
    disposition: str
    notes: str


@dataclass(frozen=True)
class TaskEvent:
    event_id: str
    kind: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    task_id: str
    artifact_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class TaskRun:
    task_id: str
    spec: TaskSpec
    interpretation: TaskInterpretation
    schema: SchemaVersion
    extraction: ExtractionResult
    coverage: CoverageReport
    status: str
    reason: str
    schema_history: tuple[SchemaVersion, ...] = ()
    extraction_history: tuple[ExtractionResult, ...] = ()
    coverage_history: tuple[CoverageReport, ...] = ()
    gap: SchemaGap | None = None
    requirement: SchemaRequirement | None = None
    candidate: SchemaCandidate | None = None
    review: ReviewDecision | None = None
    events: tuple[TaskEvent, ...] = ()
    artifacts: tuple[ArtifactRecord, ...] = ()
