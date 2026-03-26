from __future__ import annotations

from dataclasses import dataclass

from .family_bootstrap import FamilyDefinition, FamilyRegistry


RELATION_DIMENSIONS = {
    "subsidiaries",
    "competitors",
    "acquisitions",
    "regional_presence",
    "dependent_services",
    "source_entity",
    "target_entity",
    "supply_relationship",
}


@dataclass(frozen=True)
class CoverageDimensions:
    required_fields: tuple[str, ...]
    supported_fields: tuple[str, ...]
    supported_relations: tuple[str, ...]


def dimensions_for_family(registry: FamilyRegistry, family: str) -> CoverageDimensions:
    definition = _definition_for_family(registry, family)
    return CoverageDimensions(
        required_fields=definition.required_fields,
        supported_fields=definition.supported_fields,
        supported_relations=definition.supported_relations,
    )


def _definition_for_family(registry: FamilyRegistry, family: str) -> FamilyDefinition:
    if registry.has_family(family):
        return registry.get(family)
    if registry.can_bootstrap(family):
        return registry.bootstrap(family)
    return registry.get("document")
