from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class TaskSpec:
    prompt: str
    locale: str = "auto"
    requested_scope: tuple[str, ...] = ()
    caller: str = "user"
    user_id: str | None = None
    parent_task_id: str | None = None
    root_task_id: str | None = None
    branch_depth: int = 0
    branch_subject: str | None = None
    branch_role: str | None = None
    disable_subject_branching: bool = False
    execution_context: dict[str, Any] = field(default_factory=dict)
    memory_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubjectParticipant:
    subject: str
    subject_key: str
    role: str = "subject"
    aliases: tuple[str, ...] = ()
    family_hint: str = ""
    confidence: float = 1.0
    spawn: bool = True


@dataclass(frozen=True)
class TaskInterpretation:
    intent: str
    resolved_subject: str
    subject_candidates: tuple[str, ...]
    subject_aliases: tuple[str, ...]
    subject_topology: str
    branch_strategy: str
    scope_key: str
    subject_participants: tuple[SubjectParticipant, ...]
    family: str
    family_rationale: str
    requested_fields: tuple[str, ...]
    requested_relations: tuple[str, ...]
    scope_hints: tuple[str, ...]
    task_shape: str
    locale: str
    initial_family: str = ""
    family_review_rationale: str = ""
    branch_context: dict[str, Any] = field(default_factory=dict)
    memory_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchemaVersion:
    schema_id: str
    subject_key: str
    family: str
    version: int
    parent_schema_id: str | None
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    relations: tuple[str, ...]
    rationale: str
    deprecated_fields: tuple[str, ...] = ()
    deprecated_relations: tuple[str, ...] = ()
    pruning_hints: tuple[str, ...] = ()


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
    deprecated_fields: tuple[str, ...] = ()
    deprecated_relations: tuple[str, ...] = ()
    pruning_hints: tuple[str, ...] = ()


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
    recorded_at: str = field(default_factory=_utcnow_iso)


@dataclass(frozen=True)
class MemoryDocument:
    memory_id: str
    source_task_id: str
    kind: str
    user_id: str
    subject: str
    subject_key: str
    family: str
    text: str
    algorithm: str
    vector: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryHit:
    memory_id: str
    source_task_id: str
    kind: str
    user_id: str
    subject: str
    subject_key: str
    family: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserProfile:
    profile_id: str
    user_id: str
    preferred_locale: str
    family_preferences: tuple[str, ...]
    recent_subjects: tuple[str, ...]
    requested_fields: tuple[str, ...]
    requested_relations: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class TaskMemoryContext:
    user_id: str
    profile: UserProfile | None = None
    prompt_hits: tuple[MemoryHit, ...] = ()
    subject_hits: tuple[MemoryHit, ...] = ()
    context_text: str = ""


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source: str
    summary: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    subject_key: str
    family: str
    summary: str
    items: tuple[EvidenceItem, ...] = ()


@dataclass(frozen=True)
class BranchScore:
    branch_id: str
    branch_type: str
    score: float
    rationale: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicySnapshot:
    policy_id: str
    attempt: int
    dominant_issue: str
    completion_rate: float
    chosen_branch_id: str
    chosen_branch_type: str
    rationale: str
    evidence_bundle_id: str = ""
    branch_scores: tuple[BranchScore, ...] = ()
    budget: dict[str, int] = field(default_factory=dict)
    telemetry: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BranchRunSummary:
    task_id: str
    parent_task_id: str
    root_task_id: str
    relation_type: str
    ordinal: int
    resolved_subject: str
    subject_key: str
    family: str
    status: str
    reason: str
    scope_key: str = ""
    schema_id: str = ""
    schema_version: int = 0
    prompt: str = ""
    payload_summary: str = ""


@dataclass(frozen=True)
class TaskRelation:
    relation_id: str
    parent_task_id: str
    child_task_id: str
    relation_type: str
    ordinal: int
    branch_subject: str = ""
    branch_subject_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


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
    memory_context: TaskMemoryContext | None = None
    evidence_bundle: EvidenceBundle | None = None
    policy_snapshots: tuple[PolicySnapshot, ...] = ()
    branch_runs: tuple[BranchRunSummary, ...] = ()
