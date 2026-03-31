from __future__ import annotations

from .ids import next_id
from ..models import CoverageReport, SchemaGap


def build_gap(task_id: str, family: str, coverage: CoverageReport) -> SchemaGap:
    signals = tuple(coverage.missing_fields + coverage.missing_relations)
    return SchemaGap(
        gap_id=next_id("gap"),
        task_id=task_id,
        family=family,
        signals=signals,
    )
