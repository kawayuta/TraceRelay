from __future__ import annotations

from .ids import next_id
from ..models import SchemaGap, SchemaRequirement


def build_requirement(gap: SchemaGap) -> SchemaRequirement:
    summary = f"Add support for {', '.join(gap.signals)} to {gap.family}"
    return SchemaRequirement(
        requirement_id=next_id("req"),
        gap_id=gap.gap_id,
        family=gap.family,
        summary=summary,
    )
