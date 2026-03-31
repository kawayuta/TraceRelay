from __future__ import annotations

from dataclasses import asdict, replace

from .candidate_generation import build_candidate
from .coverage import CoverageEvaluator
from .evolution.gaps import build_gap
from .evolution.ids import next_id
from .evolution.requirements import build_requirement
from .extraction import Extractor
from .llm import StructuredLLM, llm_from_env
from .memory import ArtifactMemoryStore, resolve_user_id
from .models import (
    ArtifactRecord,
    CoverageReport,
    ExtractionResult,
    SchemaVersion,
    TaskEvent,
    TaskRun,
    TaskSpec,
)
from .prompt_interpretation import PromptInterpreter
from .schema_patch_planner import plan_schema_patch
from .schema_store import ArtifactSchemaStore
from .task_flow import InMemoryArtifactStore


class TaskRuntime:
    def __init__(
        self,
        llm: StructuredLLM | None = None,
        interpreter: PromptInterpreter | None = None,
        extractor: Extractor | None = None,
        coverage: CoverageEvaluator | None = None,
        artifact_store: InMemoryArtifactStore | None = None,
        schema_store: ArtifactSchemaStore | None = None,
        memory_store: ArtifactMemoryStore | None = None,
        max_value_retries: int = 2,
        max_schema_rounds: int = 3,
    ) -> None:
        active_llm = llm or llm_from_env()
        if active_llm is None:
            raise RuntimeError("TaskRuntime requires a StructuredLLM; heuristic fallback is disabled")
        self.llm = active_llm
        self.interpreter = interpreter or PromptInterpreter(active_llm)
        self.extractor = extractor or Extractor(active_llm)
        self.coverage = coverage or CoverageEvaluator()
        self.artifact_store = artifact_store or InMemoryArtifactStore()
        self.schema_store = schema_store or ArtifactSchemaStore(self.artifact_store)
        self.memory_store = memory_store or ArtifactMemoryStore(self.artifact_store)
        self.max_value_retries = max_value_retries
        self.max_schema_rounds = max_schema_rounds

    def run_task(self, spec: TaskSpec) -> TaskRun:
        task_id = next_id("task")
        self._record(
            task_id,
            "task_prompt",
            {
                "prompt": spec.prompt,
                "locale": spec.locale,
                "caller": spec.caller,
                "user_id": resolve_user_id(spec),
            },
        )

        prompt_memory = self.memory_store.build_context(spec, exclude_task_id=task_id)
        working_spec = replace(spec, memory_context=_memory_context_payload(prompt_memory))

        interpretation = self.interpreter.interpret(working_spec)
        task_memory = self.memory_store.build_context(working_spec, interpretation, exclude_task_id=task_id)
        interpretation = replace(interpretation, memory_context=_memory_context_payload(task_memory))
        self._record(
            task_id,
            "task_interpretation",
            {
                "intent": interpretation.intent,
                "resolved_subject": interpretation.resolved_subject,
                "family": interpretation.family,
                "family_rationale": interpretation.family_rationale,
                "requested_fields": list(interpretation.requested_fields),
                "requested_relations": list(interpretation.requested_relations),
                "scope_hints": list(interpretation.scope_hints),
                "memory_context": interpretation.memory_context,
            },
        )
        self.memory_store.append_task_context(task_id, task_memory)

        current_schema = self.schema_store.latest_for_family(interpretation.family)
        schema_history: list[SchemaVersion] = []
        if current_schema is None:
            schema_payload = self.llm.build_initial_schema(interpretation)
            current_schema = self.schema_store.create_or_update_schema(
                task_id,
                interpretation.family,
                schema_payload,
                parent=None,
            )
        else:
            self.schema_store.record_reference(task_id, current_schema)
        schema_history.append(current_schema)

        extraction_history: list[ExtractionResult] = []
        coverage_history: list[CoverageReport] = []
        events: list[TaskEvent] = []
        gap = requirement = candidate = review = None
        value_retries = 0
        schema_rounds = 0

        while True:
            attempt = len(extraction_history) + 1
            extraction = self.extractor.extract(
                interpretation.family,
                interpretation,
                current_schema,
                attempt=attempt,
            )
            extraction_history.append(extraction)
            self._record(
                task_id,
                "task_extraction",
                {
                    "attempt": attempt,
                    "schema_id": current_schema.schema_id,
                    "schema_version": current_schema.version,
                    "payload": extraction.payload,
                    "status": extraction.status,
                    "provider_metadata": extraction.provider_metadata,
                },
            )

            if extraction.status == "failed":
                coverage = CoverageReport((), (), (), "none")
                status = "failed"
                reason = "provider_execution_failed"
                break

            coverage = self.coverage.evaluate(current_schema, interpretation, extraction)
            coverage_history.append(coverage)
            self._record(
                task_id,
                "coverage_report",
                {
                    "schema_id": current_schema.schema_id,
                    "schema_version": current_schema.version,
                    "missing_values": list(coverage.missing_values),
                    "missing_fields": list(coverage.missing_fields),
                    "missing_relations": list(coverage.missing_relations),
                    "dominant_issue": coverage.dominant_issue,
                },
            )

            if coverage.dominant_issue == "none":
                status = "success"
                reason = "complete"
                break

            if coverage.dominant_issue == "values":
                if value_retries >= self.max_value_retries:
                    status = "partial"
                    reason = "reextract_required"
                    break
                value_retries += 1
                event = TaskEvent(
                    event_id=next_id("event"),
                    kind="reextract_requested",
                    details={
                        "attempt": attempt + 1,
                        "schema_id": current_schema.schema_id,
                        "missing_values": list(coverage.missing_values),
                    },
                )
                events.append(event)
                self._record(task_id, "task_event", {"event_id": event.event_id, "kind": event.kind, "details": event.details})
                continue

            if schema_rounds >= self.max_schema_rounds:
                status = "partial"
                reason = "schema_evolution_required"
                break

            gap = build_gap(task_id, interpretation.family, coverage)
            self._record(task_id, "schema_gap", {"gap_id": gap.gap_id, "signals": list(gap.signals)})

            requirement = build_requirement(gap)
            self._record(
                task_id,
                "schema_requirement",
                {
                    "requirement_id": requirement.requirement_id,
                    "gap_id": requirement.gap_id,
                    "summary": requirement.summary,
                },
            )

            proposed_payload = self.llm.evolve_schema(interpretation, current_schema, coverage, extraction)
            proposed_payload = _restrict_schema_evolution_payload(
                current_schema,
                proposed_payload,
                coverage,
            )
            proposed_schema = self.schema_store.create_or_update_schema(
                task_id,
                interpretation.family,
                proposed_payload,
                parent=current_schema,
            )
            schema_history.append(proposed_schema)
            candidate = build_candidate(requirement, current_schema, proposed_schema)
            if not candidate.additive_fields and not candidate.additive_relations:
                status = "partial"
                reason = "schema_evolution_required"
                break
            self._record(
                task_id,
                "schema_candidate",
                {
                    "candidate_id": candidate.candidate_id,
                    "requirement_id": candidate.requirement_id,
                    "fields": list(candidate.additive_fields),
                    "relations": list(candidate.additive_relations),
                    "rationale": candidate.rationale,
                },
            )

            review, event = plan_schema_patch(candidate, proposed_schema)
            self._record(
                task_id,
                "schema_review",
                {
                    "review_id": review.review_id,
                    "candidate_id": review.candidate_id,
                    "disposition": review.disposition,
                    "notes": review.notes,
                },
            )
            self._record(task_id, "task_event", {"event_id": event.event_id, "kind": event.kind, "details": event.details})
            events.append(event)

            current_schema = proposed_schema
            schema_rounds += 1

        self._record(
            task_id,
            "task_run",
            {
                "family": interpretation.family,
                "schema_id": current_schema.schema_id,
                "schema_version": current_schema.version,
                "status": status,
                "reason": reason,
                "attempts": len(extraction_history),
                "schema_rounds": schema_rounds,
            },
        )
        self.memory_store.learn_from_task(task_id, working_spec, interpretation, extraction_history[-1])
        task_artifacts = self.artifact_store.list_for_task(task_id)
        return TaskRun(
            task_id=task_id,
            spec=working_spec,
            interpretation=interpretation,
            schema=current_schema,
            extraction=extraction_history[-1],
            coverage=coverage,
            status=status,
            reason=reason,
            schema_history=tuple(schema_history),
            extraction_history=tuple(extraction_history),
            coverage_history=tuple(coverage_history),
            gap=gap,
            requirement=requirement,
            candidate=candidate,
            review=review,
            events=tuple(events),
            artifacts=task_artifacts,
            memory_context=task_memory,
        )

    def _record(self, task_id: str, artifact_type: str, payload: dict[str, object]) -> None:
        self.artifact_store.append(
            ArtifactRecord(
                artifact_id=next_id("artifact"),
                task_id=task_id,
                artifact_type=artifact_type,
                payload=dict(payload),
            )
        )


def _memory_context_payload(context: object) -> dict[str, object]:
    if hasattr(context, "__dataclass_fields__"):
        return asdict(context)
    return {}


def _restrict_schema_evolution_payload(
    current_schema: SchemaVersion,
    proposed_payload: dict[str, object],
    coverage: CoverageReport,
) -> dict[str, object]:
    current_required = list(current_schema.required_fields)
    current_optional = list(current_schema.optional_fields)
    current_relations = list(current_schema.relations)

    proposed_required = [str(item) for item in proposed_payload.get("required_fields", [])]
    proposed_optional = [str(item) for item in proposed_payload.get("optional_fields", [])]
    proposed_relations = [str(item) for item in proposed_payload.get("relations", [])]

    allowed_new_fields = set(coverage.missing_fields)
    allowed_new_relations = set(coverage.missing_relations)
    current_field_set = set(current_required + current_optional)
    current_relation_set = set(current_relations)

    new_required = [
        field_name
        for field_name in proposed_required
        if field_name not in current_field_set and field_name in allowed_new_fields
    ]
    new_optional = [
        field_name
        for field_name in proposed_optional
        if field_name not in current_field_set and field_name in allowed_new_fields and field_name not in new_required
    ]
    new_relations = [
        relation_name
        for relation_name in proposed_relations
        if relation_name not in current_relation_set and relation_name in allowed_new_relations
    ]

    return {
        "family": current_schema.family,
        "required_fields": current_required + new_required,
        "optional_fields": current_optional + new_optional,
        "relations": current_relations + new_relations,
        "rationale": str(proposed_payload.get("rationale", "")),
    }
