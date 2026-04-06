from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from .candidate_generation import build_candidate
from .coverage import CoverageEvaluator
from .evolution_controller import EvolutionController
from .evolution.gaps import build_gap
from .evolution.ids import next_id
from .evolution.requirements import build_requirement
from .extraction import Extractor
from .llm import StructuredLLM, llm_from_env
from .memory import ArtifactMemoryStore, normalize_subject, resolve_user_id
from .models import (
    ArtifactRecord,
    CoverageReport,
    ExtractionResult,
    PolicySnapshot,
    SchemaVersion,
    TaskEvent,
    TaskRun,
    TaskSpec,
)
from .prompt_interpretation import PromptInterpreter
from .schema_patch_planner import plan_schema_patch
from .schema_store import ArtifactSchemaStore, _normalize_schema_keys
from .task_flow import InMemoryArtifactStore


class TaskRuntime:
    def __init__(
        self,
        llm: StructuredLLM | None = None,
        interpreter: PromptInterpreter | None = None,
        extractor: Extractor | None = None,
        coverage: CoverageEvaluator | None = None,
        controller: EvolutionController | None = None,
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
        self.controller = controller or EvolutionController(self.artifact_store)
        self.schema_store = schema_store or ArtifactSchemaStore(self.artifact_store)
        self.memory_store = memory_store or ArtifactMemoryStore(self.artifact_store)
        self.max_value_retries = max_value_retries
        self.max_schema_rounds = max_schema_rounds

    def run_task(self, spec: TaskSpec, *, task_id: str | None = None) -> TaskRun:
        task_id = task_id or next_id("task")
        events: list[TaskEvent] = []
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
        evidence_bundle = self.controller.build_evidence_bundle(interpretation, task_memory)
        interpretation, task_memory, evidence_bundle = self._resolve_family_branch(
            task_id,
            working_spec,
            interpretation,
            task_memory,
            evidence_bundle,
            events,
        )
        self._record(
            task_id,
            "task_interpretation",
            {
                "intent": interpretation.intent,
                "resolved_subject": interpretation.resolved_subject,
                "family": interpretation.family,
                "initial_family": interpretation.initial_family,
                "family_rationale": interpretation.family_rationale,
                "family_review_rationale": interpretation.family_review_rationale,
                "requested_fields": list(interpretation.requested_fields),
                "requested_relations": list(interpretation.requested_relations),
                "scope_hints": list(interpretation.scope_hints),
                "memory_context": interpretation.memory_context,
            },
        )
        self._record(task_id, "task_evidence_bundle", asdict(evidence_bundle))
        if interpretation.initial_family and interpretation.initial_family != interpretation.family:
            review_event = TaskEvent(
                event_id=next_id("event"),
                kind="family_revised",
                details={
                    "from_family": interpretation.initial_family,
                    "to_family": interpretation.family,
                    "reason": interpretation.family_review_rationale or interpretation.family_rationale,
                },
            )
            events.append(review_event)
            self._record(
                task_id,
                "task_event",
                {
                    "event_id": review_event.event_id,
                    "kind": review_event.kind,
                    "details": review_event.details,
                },
            )
        self.memory_store.append_task_context(task_id, task_memory)

        subject_key = normalize_subject(interpretation.resolved_subject)
        current_schema = self.schema_store.latest_for_subject(interpretation.family, subject_key)
        schema_history: list[SchemaVersion] = []
        if current_schema is None:
            schema_payload = self.llm.build_initial_schema(interpretation)
            current_schema = self.schema_store.create_or_update_schema(
                task_id,
                subject_key,
                interpretation.family,
                schema_payload,
                parent=None,
            )
        else:
            self.schema_store.record_reference(task_id, current_schema)
        schema_history.append(current_schema)

        extraction_history: list[ExtractionResult] = []
        coverage_history: list[CoverageReport] = []
        gap = requirement = candidate = review = None
        value_retries = 0
        schema_rounds = 0
        policy_snapshots: list[PolicySnapshot] = []
        prefetched_strategy: dict[str, object] | None = None

        while True:
            attempt = len(extraction_history) + 1
            if prefetched_strategy is not None:
                current_schema = prefetched_strategy["schema"]
                prefetched_extraction = prefetched_strategy["extraction"]
                extraction = ExtractionResult(
                    payload=dict(prefetched_extraction.payload),
                    status=prefetched_extraction.status,
                    provider_metadata={
                        **dict(prefetched_extraction.provider_metadata),
                        "probe_reused": True,
                        "strategy_branch": prefetched_strategy["branch_type"],
                    },
                )
                prefetched_strategy = None
            else:
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
                policy_snapshot = self.controller.plan_branch(
                    attempt=attempt,
                    interpretation=interpretation,
                    coverage=coverage,
                    extraction_status=extraction.status,
                    value_retries=value_retries,
                    max_value_retries=self.max_value_retries,
                    schema_rounds=schema_rounds,
                    max_schema_rounds=self.max_schema_rounds,
                    evidence_bundle=evidence_bundle,
                )
                policy_snapshots.append(policy_snapshot)
                self._record(task_id, "task_branch_decision", asdict(policy_snapshot))
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
            selected_strategy: dict[str, object] | None = None
            if coverage.dominant_issue in {"values", "schema"}:
                policy_snapshot, selected_strategy = self._select_strategy_branch(
                    task_id=task_id,
                    attempt=attempt,
                    subject_key=subject_key,
                    interpretation=interpretation,
                    current_schema=current_schema,
                    extraction=extraction,
                    coverage=coverage,
                    value_retries=value_retries,
                    schema_rounds=schema_rounds,
                    evidence_bundle=evidence_bundle,
                )
            else:
                policy_snapshot = self.controller.plan_branch(
                    attempt=attempt,
                    interpretation=interpretation,
                    coverage=coverage,
                    extraction_status=extraction.status,
                    value_retries=value_retries,
                    max_value_retries=self.max_value_retries,
                    schema_rounds=schema_rounds,
                    max_schema_rounds=self.max_schema_rounds,
                    evidence_bundle=evidence_bundle,
                )
            policy_snapshots.append(policy_snapshot)
            self._record(task_id, "task_branch_decision", asdict(policy_snapshot))

            if policy_snapshot.chosen_branch_type == "complete":
                status = "success"
                reason = "complete"
                break

            if policy_snapshot.chosen_branch_type == "halt_partial":
                status = "partial"
                if coverage.dominant_issue == "values":
                    reason = "reextract_required"
                elif coverage.dominant_issue == "schema":
                    reason = "schema_evolution_required"
                else:
                    reason = "review_required"
                break

            if policy_snapshot.chosen_branch_type == "reextract":
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
                if selected_strategy is not None:
                    prefetched_strategy = selected_strategy
                continue

            if policy_snapshot.chosen_branch_type != "schema_evolution":
                status = "partial"
                reason = "review_required"
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

            if selected_strategy is not None and selected_strategy.get("branch_type") == "schema_evolution":
                proposed_payload = dict(selected_strategy["schema_payload"])
            else:
                proposed_payload = self.llm.evolve_schema(interpretation, current_schema, coverage, extraction)
                proposed_payload = _restrict_schema_evolution_payload(
                    current_schema,
                    proposed_payload,
                    coverage,
                )
            proposed_schema = self.schema_store.create_or_update_schema(
                task_id,
                subject_key,
                interpretation.family,
                proposed_payload,
                parent=current_schema,
            )
            schema_history.append(proposed_schema)
            candidate = build_candidate(requirement, current_schema, proposed_schema)
            if not (
                candidate.additive_fields
                or candidate.additive_relations
                or candidate.deprecated_fields
                or candidate.deprecated_relations
                or candidate.pruning_hints
            ):
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
                    "deprecated_fields": list(candidate.deprecated_fields),
                    "deprecated_relations": list(candidate.deprecated_relations),
                    "pruning_hints": list(candidate.pruning_hints),
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
            if selected_strategy is not None and selected_strategy.get("branch_type") == "schema_evolution":
                prefetched_strategy = {
                    "branch_type": "schema_evolution",
                    "schema": proposed_schema,
                    "extraction": selected_strategy["extraction"],
                }

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
            evidence_bundle=evidence_bundle,
            policy_snapshots=tuple(policy_snapshots),
        )

    def _resolve_family_branch(
        self,
        task_id: str,
        spec: TaskSpec,
        interpretation: Any,
        task_memory: Any,
        evidence_bundle: Any,
        events: list[TaskEvent],
    ) -> tuple[Any, Any, Any]:
        initial_family = str(interpretation.initial_family or "").strip()
        reviewed_family = str(interpretation.family or "").strip()
        if not initial_family or not reviewed_family or initial_family == reviewed_family:
            return interpretation, task_memory, evidence_bundle

        subject_key = normalize_subject(interpretation.resolved_subject)
        probes: list[dict[str, object]] = []
        for family in (reviewed_family, initial_family):
            candidate_interpretation = replace(interpretation, family=family)
            schema, schema_source = self._probe_schema(candidate_interpretation, subject_key)
            extraction = self.extractor.extract(family, candidate_interpretation, schema, attempt=1)
            if extraction.status == "failed":
                coverage = CoverageReport((), (), (), "none")
            else:
                coverage = self.coverage.evaluate(schema, candidate_interpretation, extraction)
            branch_score = self.controller.score_family_probe(
                candidate_family=family,
                interpretation=interpretation,
                coverage=coverage,
                extraction_status=extraction.status,
                evidence_bundle=evidence_bundle,
            )
            probe_payload = {
                "probe_id": next_id("probe"),
                "family": family,
                "schema_id": schema.schema_id,
                "schema_version": schema.version,
                "schema_source": schema_source,
                "status": extraction.status,
                "completion_rate": branch_score.metrics.get("completion_rate", 0.0),
                "dominant_issue": coverage.dominant_issue,
                "missing_values": list(coverage.missing_values),
                "missing_fields": list(coverage.missing_fields),
                "missing_relations": list(coverage.missing_relations),
                "payload_keys": sorted(extraction.payload.keys()),
                "score": branch_score.score,
                "rationale": branch_score.rationale,
            }
            probes.append(probe_payload)
            self._record(task_id, "task_family_probe", probe_payload)

        chosen_probe = max(probes, key=lambda item: (float(item.get("score", 0.0)), item.get("family") == reviewed_family))
        selection_payload = {
            "selection_id": next_id("selection"),
            "reviewed_family": reviewed_family,
            "initial_family": initial_family,
            "chosen_family": str(chosen_probe.get("family") or reviewed_family),
            "chosen_score": float(chosen_probe.get("score") or 0.0),
            "rationale": str(chosen_probe.get("rationale") or ""),
            "candidates": probes,
        }
        self._record(task_id, "task_family_selection", selection_payload)

        chosen_family = str(selection_payload["chosen_family"])
        if chosen_family == reviewed_family:
            return interpretation, task_memory, evidence_bundle

        selection_event = TaskEvent(
            event_id=next_id("event"),
            kind="family_branch_selected",
            details={
                "from_family": reviewed_family,
                "to_family": chosen_family,
                "initial_family": initial_family,
                "reason": selection_payload["rationale"],
            },
        )
        events.append(selection_event)
        self._record(
            task_id,
            "task_event",
            {
                "event_id": selection_event.event_id,
                "kind": selection_event.kind,
                "details": selection_event.details,
            },
        )
        updated_interpretation = replace(
            interpretation,
            family=chosen_family,
            family_rationale=str(selection_payload["rationale"]),
            family_review_rationale=str(selection_payload["rationale"]),
        )
        updated_memory = self.memory_store.build_context(spec, updated_interpretation, exclude_task_id=task_id)
        updated_interpretation = replace(updated_interpretation, memory_context=_memory_context_payload(updated_memory))
        updated_evidence = self.controller.build_evidence_bundle(updated_interpretation, updated_memory)
        return updated_interpretation, updated_memory, updated_evidence

    def _probe_schema(self, interpretation: Any, subject_key: str) -> tuple[SchemaVersion, str]:
        current_schema = self.schema_store.latest_for_subject(interpretation.family, subject_key)
        if current_schema is not None:
            return current_schema, "existing_schema"
        schema_payload = self.llm.build_initial_schema(interpretation)
        required_fields, optional_fields, relations, deprecated_fields, deprecated_relations, pruning_hints = _normalize_schema_keys(
            schema_payload.get("required_fields", []),
            schema_payload.get("optional_fields", []),
            schema_payload.get("relations", []),
            schema_payload.get("deprecated_fields", []),
            schema_payload.get("deprecated_relations", []),
            schema_payload.get("pruning_hints", []),
        )
        return (
            SchemaVersion(
                schema_id=next_id("schema_probe"),
                subject_key=subject_key,
                family=interpretation.family,
                version=1,
                parent_schema_id=None,
                required_fields=required_fields,
                optional_fields=optional_fields,
                relations=relations,
                deprecated_fields=deprecated_fields,
                deprecated_relations=deprecated_relations,
                pruning_hints=pruning_hints,
                rationale=str(schema_payload.get("rationale", "")),
            ),
            "ephemeral_initial_schema",
        )

    def _select_strategy_branch(
        self,
        *,
        task_id: str,
        attempt: int,
        subject_key: str,
        interpretation: Any,
        current_schema: SchemaVersion,
        extraction: ExtractionResult,
        coverage: CoverageReport,
        value_retries: int,
        schema_rounds: int,
        evidence_bundle: Any,
    ) -> tuple[PolicySnapshot, dict[str, object] | None]:
        heuristic_snapshot = self.controller.plan_branch(
            attempt=attempt,
            interpretation=interpretation,
            coverage=coverage,
            extraction_status=extraction.status,
            value_retries=value_retries,
            max_value_retries=self.max_value_retries,
            schema_rounds=schema_rounds,
            max_schema_rounds=self.max_schema_rounds,
            evidence_bundle=evidence_bundle,
        )
        heuristic_scores = {item.branch_type: item for item in heuristic_snapshot.branch_scores}
        candidates: list[dict[str, object]] = []
        next_attempt = attempt + 1

        reextract_hint = heuristic_scores.get("reextract")
        if reextract_hint is not None:
            reextract = self.extractor.extract(
                interpretation.family,
                interpretation,
                current_schema,
                attempt=next_attempt,
            )
            reextract_coverage = (
                CoverageReport((), (), (), "none")
                if reextract.status == "failed"
                else self.coverage.evaluate(current_schema, interpretation, reextract)
            )
            reextract_score = self.controller.score_strategy_probe(
                branch_type="reextract",
                interpretation=interpretation,
                base_coverage=coverage,
                probe_coverage=reextract_coverage,
                extraction_status=reextract.status,
                evidence_bundle=evidence_bundle,
                prior_score=reextract_hint.score,
            )
            probe_payload = {
                "probe_id": next_id("probe"),
                "attempt": attempt,
                "branch_type": "reextract",
                "score": reextract_score.score,
                "rationale": reextract_score.rationale,
                "status": reextract.status,
                "completion_rate": reextract_score.metrics.get("completion_rate", 0.0),
                "schema_id": current_schema.schema_id,
                "schema_version": current_schema.version,
                "schema_source": "current_schema",
                "missing_values": list(reextract_coverage.missing_values),
                "missing_fields": list(reextract_coverage.missing_fields),
                "missing_relations": list(reextract_coverage.missing_relations),
                "payload_keys": sorted(reextract.payload.keys()),
            }
            self._record(task_id, "task_strategy_probe", probe_payload)
            candidates.append(
                {
                    "branch_type": "reextract",
                    "score": reextract_score,
                    "schema": current_schema,
                    "extraction": reextract,
                    "coverage": reextract_coverage,
                }
            )

        evolution_hint = heuristic_scores.get("schema_evolution")
        if evolution_hint is not None:
            proposed_payload = self.llm.evolve_schema(interpretation, current_schema, coverage, extraction)
            proposed_payload = _restrict_schema_evolution_payload(current_schema, proposed_payload, coverage)
            proposed_schema = _ephemeral_schema(
                current_schema=current_schema,
                subject_key=subject_key,
                family=interpretation.family,
                payload=proposed_payload,
            )
            evolved = self.extractor.extract(
                interpretation.family,
                interpretation,
                proposed_schema,
                attempt=next_attempt,
            )
            evolved_coverage = (
                CoverageReport((), (), (), "none")
                if evolved.status == "failed"
                else self.coverage.evaluate(proposed_schema, interpretation, evolved)
            )
            evolution_score = self.controller.score_strategy_probe(
                branch_type="schema_evolution",
                interpretation=interpretation,
                base_coverage=coverage,
                probe_coverage=evolved_coverage,
                extraction_status=evolved.status,
                evidence_bundle=evidence_bundle,
                prior_score=evolution_hint.score,
            )
            probe_payload = {
                "probe_id": next_id("probe"),
                "attempt": attempt,
                "branch_type": "schema_evolution",
                "score": evolution_score.score,
                "rationale": evolution_score.rationale,
                "status": evolved.status,
                "completion_rate": evolution_score.metrics.get("completion_rate", 0.0),
                "schema_id": proposed_schema.schema_id,
                "schema_version": proposed_schema.version,
                "schema_source": "ephemeral_evolved_schema",
                "missing_values": list(evolved_coverage.missing_values),
                "missing_fields": list(evolved_coverage.missing_fields),
                "missing_relations": list(evolved_coverage.missing_relations),
                "payload_keys": sorted(evolved.payload.keys()),
                "deprecated_fields": list(proposed_schema.deprecated_fields),
                "deprecated_relations": list(proposed_schema.deprecated_relations),
                "pruning_hints": list(proposed_schema.pruning_hints),
            }
            self._record(task_id, "task_strategy_probe", probe_payload)
            candidates.append(
                {
                    "branch_type": "schema_evolution",
                    "score": evolution_score,
                    "schema": proposed_schema,
                    "schema_payload": proposed_payload,
                    "extraction": evolved,
                    "coverage": evolved_coverage,
                }
            )

        scores = [candidate["score"] for candidate in candidates]
        for branch_type, branch_score in heuristic_scores.items():
            if branch_type not in {candidate["branch_type"] for candidate in candidates}:
                scores.append(branch_score)
        policy_snapshot = self.controller.policy_snapshot_from_scores(
            attempt=attempt,
            dominant_issue=coverage.dominant_issue,
            completion_rate=heuristic_snapshot.completion_rate,
            evidence_bundle=evidence_bundle,
            scores=scores,
            budget=dict(heuristic_snapshot.budget),
            telemetry=self.controller.telemetry_snapshot(),
        )
        selection_payload = {
            "selection_id": next_id("selection"),
            "attempt": attempt,
            "chosen_branch_type": policy_snapshot.chosen_branch_type,
            "rationale": policy_snapshot.rationale,
            "candidates": [
                {
                    "branch_type": candidate["branch_type"],
                    "score": candidate["score"].score,
                    "rationale": candidate["score"].rationale,
                    "dominant_issue": candidate["coverage"].dominant_issue,
                }
                for candidate in candidates
            ]
            + [
                {
                    "branch_type": branch_type,
                    "score": branch_score.score,
                    "rationale": branch_score.rationale,
                    "dominant_issue": coverage.dominant_issue,
                }
                for branch_type, branch_score in heuristic_scores.items()
                if branch_type not in {candidate["branch_type"] for candidate in candidates}
            ],
        }
        self._record(task_id, "task_strategy_selection", selection_payload)
        selected_candidate = next(
            (candidate for candidate in candidates if candidate["branch_type"] == policy_snapshot.chosen_branch_type),
            None,
        )
        return policy_snapshot, selected_candidate

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
    current_deprecated_fields = list(current_schema.deprecated_fields)
    current_deprecated_relations = list(current_schema.deprecated_relations)
    current_pruning_hints = list(current_schema.pruning_hints)

    proposed_required = [str(item) for item in proposed_payload.get("required_fields", [])]
    proposed_optional = [str(item) for item in proposed_payload.get("optional_fields", [])]
    proposed_relations = [str(item) for item in proposed_payload.get("relations", [])]
    proposed_deprecated_fields = [str(item) for item in proposed_payload.get("deprecated_fields", [])]
    proposed_deprecated_relations = [str(item) for item in proposed_payload.get("deprecated_relations", [])]
    proposed_pruning_hints = [str(item) for item in proposed_payload.get("pruning_hints", [])]

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
    new_deprecated_fields = [
        field_name
        for field_name in proposed_deprecated_fields
        if field_name in current_field_set and field_name not in set(current_deprecated_fields)
    ]
    new_deprecated_relations = [
        relation_name
        for relation_name in proposed_deprecated_relations
        if relation_name in current_relation_set and relation_name not in set(current_deprecated_relations)
    ]
    new_pruning_hints = [
        hint
        for hint in proposed_pruning_hints
        if hint and hint not in set(current_pruning_hints)
    ]

    return {
        "family": current_schema.family,
        "required_fields": current_required + new_required,
        "optional_fields": current_optional + new_optional,
        "relations": current_relations + new_relations,
        "deprecated_fields": current_deprecated_fields + new_deprecated_fields,
        "deprecated_relations": current_deprecated_relations + new_deprecated_relations,
        "pruning_hints": current_pruning_hints + new_pruning_hints,
        "rationale": str(proposed_payload.get("rationale", "")),
    }


def _ephemeral_schema(
    *,
    current_schema: SchemaVersion,
    subject_key: str,
    family: str,
    payload: dict[str, object],
) -> SchemaVersion:
    required_fields, optional_fields, relations, deprecated_fields, deprecated_relations, pruning_hints = _normalize_schema_keys(
        payload.get("required_fields", []),
        payload.get("optional_fields", []),
        payload.get("relations", []),
        payload.get("deprecated_fields", []),
        payload.get("deprecated_relations", []),
        payload.get("pruning_hints", []),
    )
    return SchemaVersion(
        schema_id=next_id("schema_probe"),
        subject_key=subject_key,
        family=family,
        version=current_schema.version + 1,
        parent_schema_id=current_schema.schema_id,
        required_fields=required_fields,
        optional_fields=optional_fields,
        relations=relations,
        deprecated_fields=deprecated_fields,
        deprecated_relations=deprecated_relations,
        pruning_hints=pruning_hints,
        rationale=str(payload.get("rationale", "")),
    )
