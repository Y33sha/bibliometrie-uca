"""Aggregate root ``Structure`` — entité métier d'une structure de
recherche / d'enseignement (laboratoire, école doctorale, université,
hôpital, …).

Identité = `id` (clé surrogate). Identifiant naturel : `code`
(unique). Une structure agrège ses formes de noms (`name_forms`) ainsi
que ses identifiants d'API externes (`api_ids` JSONB côté schéma — RoR,
RNSR, HAL collection).

La logique métier touchant aux structures (matching, désambiguïsation,
règles sur la hiérarchie `structure_relations`) vit ici.
"""

from dataclasses import dataclass, field

from domain.structures.name_forms import StructureNameForm


@dataclass(slots=True)
class Structure:
    """Structure de recherche / d'enseignement (aggregate root)."""

    id: int | None
    code: str
    name: str
    structure_type: str
    acronym: str | None = None
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict[str, list[str]] | None = None
    name_forms: tuple[StructureNameForm, ...] = field(default=())
