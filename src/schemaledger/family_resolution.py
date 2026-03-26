from __future__ import annotations

from .family_bootstrap import FamilyRegistry
from .models import FamilyCandidate, FamilyDecision, TaskInterpretation


class FamilyResolver:
    def resolve(self, interpretation: TaskInterpretation, registry: FamilyRegistry) -> FamilyDecision:
        rescored = [self._rescore(candidate, interpretation, registry) for candidate in interpretation.family_candidates]
        rescored.sort(key=lambda item: item.score, reverse=True)
        chosen = rescored[0]
        return FamilyDecision(
            chosen_family=chosen.family,
            confidence=round(chosen.score, 3),
            bootstrap_required=not registry.has_family(chosen.family) and registry.can_bootstrap(chosen.family),
            candidates=tuple(rescored),
            rejection_reasons=(),
        )

    def _rescore(
        self,
        candidate: FamilyCandidate,
        interpretation: TaskInterpretation,
        registry: FamilyRegistry,
    ) -> FamilyCandidate:
        score = candidate.score
        reasons = list(candidate.reasons)
        if registry.has_family(candidate.family):
            score += 0.03
            reasons.append("installed")
        elif registry.can_bootstrap(candidate.family):
            score += 0.01
            reasons.append("bootstrap_available")
        else:
            score -= 0.1
            reasons.append("unsupported")
        if candidate.family == "document" and interpretation.family_candidates and interpretation.family_candidates[0].family != "document":
            score -= 0.25
            reasons.append("deprioritized_fallback")
        if candidate.family == "organization" and interpretation.resolved_subject.count(" と ") == 1:
            score -= 0.2
            reasons.append("multi_entity_penalty")
        return FamilyCandidate(
            family=candidate.family,
            score=max(min(score, 0.99), 0.0),
            reasons=tuple(reasons),
        )
