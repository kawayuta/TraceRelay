from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from schemaledger.models import ExtractionResult


class FakeStructuredLLM:
    def interpret_task(self, spec):
        prompt = spec.prompt
        if "Google" in prompt:
            return {
                "intent": "investigate_subject",
                "resolved_subject": "Google",
                "subject_candidates": ["Google"],
                "family": "organization",
                "family_rationale": "The prompt asks for a company profile and organization relationships.",
                "requested_fields": [
                    "overview",
                    "business_lines",
                    "leadership",
                    "major_risks",
                    "regional_presence",
                ],
                "requested_relations": ["subsidiaries", "competitors", "acquisitions"],
                "scope_hints": [
                    "overview",
                    "business_lines",
                    "leadership",
                    "subsidiaries",
                    "acquisitions",
                    "competitors",
                    "major_risks",
                    "regional_presence",
                ],
                "task_shape": "subject_analysis",
                "locale": "ja",
            }
        if "Macross" in prompt:
            return {
                "intent": "investigate_subject",
                "resolved_subject": "Macross",
                "subject_candidates": ["Macross"],
                "family": "media_work",
                "family_rationale": "The prompt targets a media franchise work and viewing structure.",
                "requested_fields": [
                    "overview",
                    "series",
                    "viewing_order",
                    "chronological_order",
                    "characters",
                    "mecha",
                    "songs",
                    "staff",
                ],
                "requested_relations": [],
                "scope_hints": [
                    "overview",
                    "series",
                    "viewing_order",
                    "chronological_order",
                    "characters",
                    "mecha",
                    "songs",
                    "staff",
                ],
                "task_shape": "subject_analysis",
                "locale": "ja",
            }
        if "少子化対策" in prompt:
            return {
                "intent": "analyze_policy",
                "resolved_subject": "日本の少子化対策の政策パッケージ",
                "subject_candidates": ["日本の少子化対策の政策パッケージ"],
                "family": "policy",
                "family_rationale": "The task requests a policy package analysis.",
                "requested_fields": [
                    "policy_objective",
                    "target_population",
                    "implementing_bodies",
                    "measures",
                    "funding",
                    "metrics",
                    "issues",
                ],
                "requested_relations": [],
                "scope_hints": [
                    "policy_objective",
                    "target_population",
                    "implementing_bodies",
                    "measures",
                    "funding",
                    "metrics",
                    "issues",
                ],
                "task_shape": "subject_analysis",
                "locale": "ja",
            }
        if "API障害" in prompt:
            return {
                "intent": "analyze_incident",
                "resolved_subject": "API障害",
                "subject_candidates": ["API障害"],
                "family": "system_incident",
                "family_rationale": "The task asks for incident impact, cause, and mitigation details.",
                "requested_fields": ["impact_scope", "root_cause_hypothesis", "timeline", "prevention"],
                "requested_relations": ["dependent_services"],
                "scope_hints": [
                    "impact_scope",
                    "root_cause_hypothesis",
                    "dependent_services",
                    "timeline",
                    "prevention",
                ],
                "task_shape": "subject_analysis",
                "locale": "ja",
            }
        if "TSMC" in prompt and "NVIDIA" in prompt:
            return {
                "intent": "investigate_subject",
                "resolved_subject": "TSMC と NVIDIA",
                "subject_candidates": ["TSMC と NVIDIA", "TSMC", "NVIDIA"],
                "family": "relationship",
                "family_rationale": "The task centers on an inter-company relationship.",
                "requested_fields": [
                    "relation_type",
                    "product_categories",
                    "dependency_level",
                    "major_risks",
                    "substitutability",
                ],
                "requested_relations": ["source_entity", "target_entity", "supply_relationship"],
                "scope_hints": [
                    "relation_type",
                    "product_categories",
                    "dependency_level",
                    "major_risks",
                    "substitutability",
                    "source_entity",
                    "target_entity",
                    "supply_relationship",
                ],
                "task_shape": "subject_analysis",
                "locale": "ja",
            }
        return {
            "intent": "investigate_subject",
            "resolved_subject": "ACME Hypergrid",
            "subject_candidates": ["ACME Hypergrid"],
            "family": "organization",
            "family_rationale": "The task asks for an organization overview.",
            "requested_fields": ["overview", "business_lines"],
            "requested_relations": [],
            "scope_hints": ["overview", "business_lines"],
            "task_shape": "subject_analysis",
            "locale": "en",
        }

    def build_initial_schema(self, interpretation):
        family = interpretation.family
        if family == "organization":
            return {
                "family": family,
                "required_fields": ["overview", "business_lines"],
                "optional_fields": ["leadership", "major_risks"],
                "relations": ["subsidiaries", "competitors"],
                "rationale": "Initial schema covers the common organization profile.",
            }
        if family == "media_work":
            return {
                "family": family,
                "required_fields": ["overview", "series"],
                "optional_fields": [
                    "viewing_order",
                    "chronological_order",
                    "characters",
                    "mecha",
                    "songs",
                    "staff",
                ],
                "relations": [],
                "rationale": "Initial media schema covers the requested work structure.",
            }
        if family == "policy":
            return {
                "family": family,
                "required_fields": ["policy_objective", "target_population", "measures"],
                "optional_fields": ["implementing_bodies", "funding", "metrics", "issues"],
                "relations": [],
                "rationale": "Initial policy schema covers the requested policy facets.",
            }
        if family == "system_incident":
            return {
                "family": family,
                "required_fields": ["impact_scope", "timeline", "prevention"],
                "optional_fields": ["root_cause_hypothesis"],
                "relations": ["dependent_services"],
                "rationale": "Initial incident schema covers the requested incident facets.",
            }
        if family == "relationship":
            return {
                "family": family,
                "required_fields": ["relation_type", "product_categories", "dependency_level"],
                "optional_fields": ["major_risks", "substitutability"],
                "relations": ["source_entity", "target_entity", "supply_relationship"],
                "rationale": "Initial relationship schema covers the requested relationship facets.",
            }
        return {
            "family": family,
            "required_fields": list(interpretation.requested_fields),
            "optional_fields": [],
            "relations": list(interpretation.requested_relations),
            "rationale": "Generic initial schema.",
        }

    def evolve_schema(self, interpretation, schema, coverage, extraction):
        current_fields = list(schema.required_fields + schema.optional_fields)
        current_relations = list(schema.relations)
        return {
            "family": interpretation.family,
            "required_fields": list(schema.required_fields),
            "optional_fields": current_fields[len(schema.required_fields) :] + list(coverage.missing_fields),
            "relations": current_relations + list(coverage.missing_relations),
            "rationale": "The task requires additional keys and relations to satisfy the requested scope.",
        }

    def extract_task(self, family, interpretation, schema, attempt):
        payload = {}
        for field_name in schema.required_fields + schema.optional_fields:
            payload[field_name] = self._field_value(interpretation, field_name, attempt)
        for relation_name in schema.relations:
            payload[relation_name] = self._relation_value(interpretation, relation_name, attempt)
        return ExtractionResult(
            payload=payload,
            status="success",
            provider_metadata={"provider": "fake_llm", "attempt": attempt},
        )

    def _field_value(self, interpretation, field_name, attempt):
        subject = interpretation.resolved_subject
        if interpretation.family == "media_work" and attempt == 1 and field_name in {
            "characters",
            "mecha",
            "songs",
            "staff",
            "chronological_order",
        }:
            return []
        if field_name == "overview":
            return f"{subject} overview"
        if field_name == "business_lines":
            return ["core business", "adjacent business"]
        if field_name == "leadership":
            return ["executive leadership"]
        if field_name == "major_risks":
            return ["major risk"]
        if field_name == "regional_presence":
            return ["APAC", "NA"]
        if field_name == "series":
            return ["main series", "spinoff"]
        if field_name == "viewing_order":
            return ["release order"]
        if field_name == "chronological_order":
            return ["story order"]
        if field_name == "characters":
            return ["lead character"]
        if field_name == "mecha":
            return ["signature mecha"]
        if field_name == "songs":
            return ["theme song"]
        if field_name == "staff":
            return ["key staff"]
        if field_name == "policy_objective":
            return "policy objective"
        if field_name == "target_population":
            return ["target population"]
        if field_name == "implementing_bodies":
            return ["government"]
        if field_name == "measures":
            return ["policy measure"]
        if field_name == "funding":
            return ["public budget"]
        if field_name == "metrics":
            return ["metric"]
        if field_name == "issues":
            return ["policy issue"]
        if field_name == "impact_scope":
            return "degraded API responses"
        if field_name == "root_cause_hypothesis":
            return "upstream dependency saturation"
        if field_name == "timeline":
            return ["00:00 detect", "00:10 mitigate"]
        if field_name == "prevention":
            return ["improve failover"]
        if field_name == "relation_type":
            return "supply_chain_relation"
        if field_name == "product_categories":
            return ["advanced semiconductors"]
        if field_name == "dependency_level":
            return "high"
        if field_name == "substitutability":
            return "limited"
        return f"{field_name} for {subject}"

    def _relation_value(self, interpretation, relation_name, attempt):
        if relation_name == "subsidiaries":
            return ["major subsidiary"]
        if relation_name == "competitors":
            return ["major competitor"]
        if relation_name == "acquisitions":
            return ["major acquisition"]
        if relation_name == "dependent_services":
            return ["auth", "database"]
        if relation_name == "source_entity":
            return interpretation.subject_candidates[1] if len(interpretation.subject_candidates) > 1 else interpretation.resolved_subject
        if relation_name == "target_entity":
            return interpretation.subject_candidates[2] if len(interpretation.subject_candidates) > 2 else interpretation.resolved_subject
        if relation_name == "supply_relationship":
            return "strategic supplier relationship"
        return [relation_name]


@pytest.fixture
def fake_llm():
    return FakeStructuredLLM()
