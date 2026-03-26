from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyDefinition:
    name: str
    required_fields: tuple[str, ...]
    supported_fields: tuple[str, ...]
    supported_relations: tuple[str, ...]


class FamilyRegistry:
    def __init__(
        self,
        installed: dict[str, FamilyDefinition] | None = None,
        templates: dict[str, FamilyDefinition] | None = None,
    ) -> None:
        self._installed = dict(installed or {})
        self._templates = dict(templates or {})

    def has_family(self, family: str) -> bool:
        return family in self._installed

    def can_bootstrap(self, family: str) -> bool:
        return family in self._templates

    def get(self, family: str) -> FamilyDefinition:
        if family in self._installed:
            return self._installed[family]
        raise KeyError(f"Family {family!r} is not installed")

    def bootstrap(self, family: str) -> FamilyDefinition:
        if family in self._installed:
            return self._installed[family]
        if family not in self._templates:
            raise KeyError(f"Family {family!r} cannot be bootstrapped")
        definition = self._templates[family]
        self._installed[family] = definition
        return definition

    @classmethod
    def default(cls) -> "FamilyRegistry":
        templates = _family_templates()
        installed = {
            name: templates[name]
            for name in ("organization", "media_work", "document")
        }
        return cls(installed=installed, templates=templates)


def _family_templates() -> dict[str, FamilyDefinition]:
    return {
        "document": FamilyDefinition(
            name="document",
            required_fields=("summary",),
            supported_fields=("summary",),
            supported_relations=(),
        ),
        "organization": FamilyDefinition(
            name="organization",
            required_fields=("overview", "business_lines"),
            supported_fields=(
                "overview",
                "business_lines",
                "leadership",
                "major_risks",
            ),
            supported_relations=("subsidiaries", "competitors"),
        ),
        "media_work": FamilyDefinition(
            name="media_work",
            required_fields=("overview", "series"),
            supported_fields=(
                "overview",
                "series",
                "viewing_order",
                "chronological_order",
                "characters",
                "mecha",
                "songs",
                "staff",
            ),
            supported_relations=(),
        ),
        "franchise": FamilyDefinition(
            name="franchise",
            required_fields=("overview", "entries"),
            supported_fields=("overview", "entries", "timeline"),
            supported_relations=("works",),
        ),
        "policy": FamilyDefinition(
            name="policy",
            required_fields=("policy_objective", "target_population", "measures"),
            supported_fields=(
                "policy_objective",
                "target_population",
                "implementing_bodies",
                "measures",
                "funding",
                "metrics",
                "issues",
            ),
            supported_relations=(),
        ),
        "system_incident": FamilyDefinition(
            name="system_incident",
            required_fields=("impact_scope", "timeline", "prevention"),
            supported_fields=(
                "impact_scope",
                "root_cause_hypothesis",
                "timeline",
                "prevention",
            ),
            supported_relations=("dependent_services",),
        ),
        "relationship": FamilyDefinition(
            name="relationship",
            required_fields=(
                "relation_type",
                "product_categories",
                "dependency_level",
            ),
            supported_fields=(
                "relation_type",
                "product_categories",
                "dependency_level",
                "major_risks",
                "substitutability",
            ),
            supported_relations=("source_entity", "target_entity", "supply_relationship"),
        ),
    }
