from __future__ import annotations

from .llm import StructuredLLM
from .models import ExtractionResult, SchemaVersion, TaskInterpretation


class Extractor:
    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    def extract(
        self,
        family: str,
        interpretation: TaskInterpretation,
        schema: SchemaVersion,
        attempt: int = 1,
    ) -> ExtractionResult:
        return self.llm.extract_task(family, interpretation, schema, attempt)
