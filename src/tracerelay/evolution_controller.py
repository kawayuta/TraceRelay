from __future__ import annotations

from collections import defaultdict
from typing import Any

from .evolution.ids import next_id
from .memory import normalize_subject
from .models import (
    BranchScore,
    CoverageReport,
    EvidenceBundle,
    EvidenceItem,
    PolicySnapshot,
    TaskInterpretation,
    TaskMemoryContext,
)


class EvolutionController:
    def __init__(self, artifact_store: Any | None = None) -> None:
        self.artifact_store = artifact_store

    def build_evidence_bundle(
        self,
        interpretation: TaskInterpretation,
        memory_context: TaskMemoryContext | None,
    ) -> EvidenceBundle:
        items = [
            EvidenceItem(
                evidence_id=next_id("evidence"),
                source="interpretation",
                summary=f"resolved subject: {interpretation.resolved_subject}",
                confidence=1.0,
                metadata={"family": interpretation.family, "task_shape": interpretation.task_shape},
            )
        ]
        if interpretation.family_review_rationale:
            confidence = 0.9 if interpretation.initial_family and interpretation.initial_family != interpretation.family else 0.75
            items.append(
                EvidenceItem(
                    evidence_id=next_id("evidence"),
                    source="family_review",
                    summary=interpretation.family_review_rationale,
                    confidence=confidence,
                    metadata={
                        "initial_family": interpretation.initial_family,
                        "final_family": interpretation.family,
                    },
                )
            )
        branch_context = dict(interpretation.branch_context)
        branch_children = [dict(item) for item in branch_context.get("children", [])]
        if branch_children:
            items.append(
                EvidenceItem(
                    evidence_id=next_id("evidence"),
                    source="subject_branches",
                    summary=(
                        f"{len(branch_children)} branch task(s) materialized for "
                        f"{interpretation.resolved_subject}"
                    ),
                    confidence=0.8,
                    metadata={
                        "scope_key": interpretation.scope_key,
                        "branch_strategy": interpretation.branch_strategy,
                        "child_task_ids": [str(item.get("task_id", "")) for item in branch_children],
                    },
                )
            )
        if memory_context and memory_context.profile is not None:
            profile = memory_context.profile
            items.append(
                EvidenceItem(
                    evidence_id=next_id("evidence"),
                    source="user_profile",
                    summary=profile.summary,
                    confidence=0.55,
                    metadata={
                        "preferred_locale": profile.preferred_locale,
                        "family_preferences": list(profile.family_preferences),
                    },
                )
            )
        if memory_context:
            for hit in memory_context.prompt_hits[:2]:
                items.append(
                    EvidenceItem(
                        evidence_id=next_id("evidence"),
                        source="prompt_memory",
                        summary=hit.text,
                        confidence=_clamp_confidence(hit.score),
                        metadata={"subject": hit.subject, "family": hit.family, "score": hit.score},
                    )
                )
            for hit in memory_context.subject_hits[:3]:
                items.append(
                    EvidenceItem(
                        evidence_id=next_id("evidence"),
                        source="subject_memory",
                        summary=hit.text,
                        confidence=_clamp_confidence(hit.score + 0.1),
                        metadata={"subject": hit.subject, "family": hit.family, "score": hit.score},
                    )
                )
        subject_key = normalize_subject(interpretation.resolved_subject)
        summary = (
            f"{len(items)} evidence item(s) for {interpretation.resolved_subject} "
            f"as {interpretation.family or 'n/a'}"
        )
        return EvidenceBundle(
            bundle_id=next_id("bundle"),
            subject_key=subject_key,
            family=interpretation.family,
            summary=summary,
            items=tuple(items),
        )

    def telemetry_snapshot(self) -> dict[str, dict[str, float]]:
        if self.artifact_store is None or not hasattr(self.artifact_store, "all_artifacts"):
            return {"branch_success_rates": {}, "family_success_rates": {}}
        artifacts = list(self.artifact_store.all_artifacts())
        latest_runs: dict[str, dict[str, object]] = {}
        for artifact in artifacts:
            if artifact.artifact_type == "task_run":
                latest_runs[artifact.task_id] = dict(artifact.payload)
        branch_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        family_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for artifact in artifacts:
            payload = dict(artifact.payload)
            if artifact.artifact_type == "task_branch_decision":
                branch_type = str(payload.get("chosen_branch_type") or "").strip()
                if not branch_type:
                    continue
                branch_counts[branch_type][0] += 1
                if _branch_decision_succeeded(branch_type, latest_runs.get(artifact.task_id, {})):
                    branch_counts[branch_type][1] += 1
            elif artifact.artifact_type == "task_family_selection":
                family = str(payload.get("chosen_family") or "").strip()
                if not family:
                    continue
                family_counts[family][0] += 1
                if str(latest_runs.get(artifact.task_id, {}).get("status") or "") == "success":
                    family_counts[family][1] += 1
        return {
            "branch_success_rates": {
                branch_type: round(successes / seen, 4)
                for branch_type, (seen, successes) in branch_counts.items()
                if seen > 0
            },
            "family_success_rates": {
                family: round(successes / seen, 4)
                for family, (seen, successes) in family_counts.items()
                if seen > 0
            },
        }

    def score_family_probe(
        self,
        *,
        candidate_family: str,
        interpretation: TaskInterpretation,
        coverage: CoverageReport,
        extraction_status: str,
        evidence_bundle: EvidenceBundle | None,
    ) -> BranchScore:
        telemetry = self.telemetry_snapshot()
        completion_rate = _completion_rate(coverage, interpretation)
        evidence_support = _family_evidence_support(candidate_family, evidence_bundle)
        issue_penalty = 0.0
        if extraction_status == "failed":
            issue_penalty = 0.45
        elif coverage.dominant_issue == "schema":
            issue_penalty = 0.22
        elif coverage.dominant_issue == "values":
            issue_penalty = 0.1
        review_alignment = 0.06 if candidate_family == interpretation.family else 0.0
        initial_alignment = 0.04 if candidate_family == interpretation.initial_family else 0.0
        telemetry_bonus = _history_adjustment(telemetry["family_success_rates"].get(candidate_family))
        score = max(
            0.0,
            0.62 * completion_rate + evidence_support + review_alignment + initial_alignment + telemetry_bonus - issue_penalty,
        )
        rationale = (
            f"{candidate_family} reached completion {completion_rate:.2f} with "
            f"{coverage.dominant_issue or 'none'} gaps and evidence support {evidence_support:.2f}."
        )
        return BranchScore(
            branch_id=next_id("branch"),
            branch_type=f"family::{candidate_family}",
            score=round(score, 4),
            rationale=rationale,
            metrics={
                "completion_rate": round(completion_rate, 4),
                "evidence_support": round(evidence_support, 4),
                "telemetry_bonus": round(telemetry_bonus, 4),
            },
        )

    def score_strategy_probe(
        self,
        *,
        branch_type: str,
        interpretation: TaskInterpretation,
        base_coverage: CoverageReport,
        probe_coverage: CoverageReport,
        extraction_status: str,
        evidence_bundle: EvidenceBundle | None,
        prior_score: float,
    ) -> BranchScore:
        telemetry = self.telemetry_snapshot()
        completion_rate = _completion_rate(probe_coverage, interpretation)
        evidence_strength = _generic_evidence_support(evidence_bundle)
        telemetry_bonus = _history_adjustment(telemetry["branch_success_rates"].get(branch_type))
        value_gain = _coverage_gain(base_coverage.missing_values, probe_coverage.missing_values)
        structure_gain = _coverage_gain(
            base_coverage.missing_fields + base_coverage.missing_relations,
            probe_coverage.missing_fields + probe_coverage.missing_relations,
        )
        issue_penalty = 0.0
        if extraction_status == "failed":
            issue_penalty = 0.45
        elif probe_coverage.dominant_issue == "schema":
            issue_penalty = 0.18
        elif probe_coverage.dominant_issue == "values":
            issue_penalty = 0.08
        cost_penalty = 0.1 if branch_type == "schema_evolution" else 0.04
        score = max(
            0.0,
            prior_score
            + (0.24 * completion_rate)
            + (0.16 * value_gain)
            + (0.18 * structure_gain)
            + evidence_strength
            + telemetry_bonus
            - issue_penalty
            - cost_penalty,
        )
        rationale = (
            f"{branch_type} forecast completion {completion_rate:.2f}, "
            f"value gain {value_gain:.2f}, structure gain {structure_gain:.2f}."
        )
        return BranchScore(
            branch_id=next_id("branch"),
            branch_type=branch_type,
            score=round(score, 4),
            rationale=rationale,
            metrics={
                "completion_rate": round(completion_rate, 4),
                "value_gain": round(value_gain, 4),
                "structure_gain": round(structure_gain, 4),
                "evidence_support": round(evidence_strength, 4),
                "telemetry_bonus": round(telemetry_bonus, 4),
            },
        )

    def plan_branch(
        self,
        *,
        attempt: int,
        interpretation: TaskInterpretation,
        coverage: CoverageReport,
        extraction_status: str,
        value_retries: int,
        max_value_retries: int,
        schema_rounds: int,
        max_schema_rounds: int,
        evidence_bundle: EvidenceBundle | None,
    ) -> PolicySnapshot:
        telemetry = self.telemetry_snapshot()
        completion_rate = _completion_rate(coverage, interpretation)
        budget = {
            "value_retries_used": value_retries,
            "value_retries_remaining": max(max_value_retries - value_retries, 0),
            "schema_rounds_used": schema_rounds,
            "schema_rounds_remaining": max(max_schema_rounds - schema_rounds, 0),
        }
        scores: list[BranchScore] = []

        def add(branch_type: str, score: float, rationale: str) -> None:
            telemetry_bonus = _history_adjustment(telemetry["branch_success_rates"].get(branch_type))
            scores.append(
                BranchScore(
                    branch_id=next_id("branch"),
                    branch_type=branch_type,
                    score=round(score + telemetry_bonus, 4),
                    rationale=rationale,
                    metrics={
                        "completion_rate": round(completion_rate, 4),
                        "value_retry_utilization": _safe_ratio(value_retries, max_value_retries),
                        "schema_round_utilization": _safe_ratio(schema_rounds, max_schema_rounds),
                        "telemetry_bonus": round(telemetry_bonus, 4),
                    },
                )
            )

        if extraction_status == "failed":
            add("halt_failed", 1.0, "Provider execution failed before a recoverable branch could continue.")
        elif coverage.dominant_issue == "none":
            add("complete", 1.0, "Coverage is complete, so no further branch should run.")
        elif coverage.dominant_issue == "values":
            if value_retries < max_value_retries:
                add(
                    "reextract",
                    0.78 + (0.12 * completion_rate) - (0.18 * _safe_ratio(value_retries, max_value_retries)),
                    "Value gaps remain and the retry budget still allows another extraction pass.",
                )
            halt_bonus = 0.35 if value_retries >= max_value_retries else 0.0
            add(
                "halt_partial",
                0.25 + (0.2 * completion_rate) + halt_bonus,
                "Stop when retry budget is exhausted or the remaining value gaps no longer justify another pass.",
            )
        elif coverage.dominant_issue == "schema":
            if schema_rounds < max_schema_rounds:
                add(
                    "schema_evolution",
                    0.82 + (0.1 * completion_rate) - (0.16 * _safe_ratio(schema_rounds, max_schema_rounds)),
                    "Structural gaps remain and schema evolution still has budget to add the missing shape.",
                )
            if value_retries < max_value_retries:
                add(
                    "reextract",
                    0.32 + (0.08 * completion_rate),
                    "Try one more same-schema extraction when the gap may still be evidence quality rather than structure.",
                )
            halt_bonus = 0.35 if schema_rounds >= max_schema_rounds else 0.0
            add(
                "halt_partial",
                0.24 + (0.2 * completion_rate) + halt_bonus,
                "Stop when schema rounds are exhausted or the remaining structure gap must be reviewed externally.",
            )
        else:
            add("halt_partial", 0.3 + (0.15 * completion_rate), "No safe continuation branch was identified.")
        return self.policy_snapshot_from_scores(
            attempt=attempt,
            dominant_issue=coverage.dominant_issue,
            completion_rate=completion_rate,
            evidence_bundle=evidence_bundle,
            scores=scores,
            budget=budget,
            telemetry=telemetry,
        )

    def policy_snapshot_from_scores(
        self,
        *,
        attempt: int,
        dominant_issue: str,
        completion_rate: float,
        evidence_bundle: EvidenceBundle | None,
        scores: list[BranchScore],
        budget: dict[str, int],
        telemetry: dict[str, dict[str, float]],
    ) -> PolicySnapshot:
        chosen = max(scores, key=lambda item: (item.score, item.branch_type))
        rationale = (
            f"Chose {chosen.branch_type} on attempt {attempt} with dominant issue "
            f"{dominant_issue or 'none'} and completion {completion_rate:.2f}."
        )
        flat_telemetry = {
            f"branch::{key}": value for key, value in telemetry.get("branch_success_rates", {}).items()
        }
        flat_telemetry.update(
            {f"family::{key}": value for key, value in telemetry.get("family_success_rates", {}).items()}
        )
        return PolicySnapshot(
            policy_id=next_id("policy"),
            attempt=attempt,
            dominant_issue=dominant_issue,
            completion_rate=round(completion_rate, 4),
            chosen_branch_id=chosen.branch_id,
            chosen_branch_type=chosen.branch_type,
            rationale=rationale,
            evidence_bundle_id="" if evidence_bundle is None else evidence_bundle.bundle_id,
            branch_scores=tuple(scores),
            budget=budget,
            telemetry=flat_telemetry,
        )


def _branch_decision_succeeded(branch_type: str, run: dict[str, object]) -> bool:
    status = str(run.get("status") or "")
    reason = str(run.get("reason") or "")
    if branch_type == "complete":
        return status == "success" and reason == "complete"
    if branch_type in {"reextract", "schema_evolution"}:
        return status == "success"
    if branch_type == "halt_partial":
        return status == "partial"
    if branch_type == "halt_failed":
        return status == "failed"
    return False


def _completion_rate(coverage: CoverageReport, interpretation: TaskInterpretation) -> float:
    requested_slots = len(set(interpretation.requested_fields) | set(interpretation.requested_relations))
    missing_slots = (
        len(set(coverage.missing_values))
        + len(set(coverage.missing_fields))
        + len(set(coverage.missing_relations))
    )
    denominator = max(requested_slots, missing_slots, 1)
    completed = max(denominator - missing_slots, 0)
    return round(completed / denominator, 4)


def _clamp_confidence(score: float) -> float:
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return round(score, 4)


def _safe_ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 4)


def _family_evidence_support(candidate_family: str, evidence_bundle: EvidenceBundle | None) -> float:
    if evidence_bundle is None:
        return 0.0
    support = 0.0
    for item in evidence_bundle.items:
        metadata = dict(item.metadata)
        if metadata.get("family") == candidate_family:
            support += 0.06 * item.confidence
        if metadata.get("final_family") == candidate_family:
            support += 0.1 * item.confidence
        if metadata.get("initial_family") == candidate_family:
            support += 0.08 * item.confidence
    return round(min(support, 0.28), 4)


def _generic_evidence_support(evidence_bundle: EvidenceBundle | None) -> float:
    if evidence_bundle is None or not evidence_bundle.items:
        return 0.0
    avg_confidence = sum(item.confidence for item in evidence_bundle.items) / len(evidence_bundle.items)
    return round(min(avg_confidence * 0.05, 0.05), 4)


def _history_adjustment(rate: float | None) -> float:
    if rate is None:
        return 0.0
    return round((rate - 0.5) * 0.12, 4)


def _coverage_gain(before: tuple[str, ...], after: tuple[str, ...]) -> float:
    before_count = len(set(before))
    if before_count <= 0:
        return 0.0
    after_count = len(set(after))
    return round(max(before_count - after_count, 0) / before_count, 4)
