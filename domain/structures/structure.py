"""Aggregate root ``Structure`` — entité métier d'une structure de
recherche / d'enseignement (laboratoire, école doctorale, université,
hôpital, …).

Identité = `id` (clé surrogate). Identifiant naturel : `code`
(unique). Une structure agrège ses formes de noms (`name_forms`) ainsi
que ses identifiants externes (RorId, HalCollection) et un dict
`api_ids` JSONB pour les identifiants des sources qui ne méritent pas
encore leur VO (clés métier : `openalex`, `wos`, `scanr`, `theses`,
`hal`).

La logique métier touchant aux structures (matching, désambiguïsation,
règles sur la hiérarchie `structure_relations`) vit ici.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from domain.structures.identifiers import HalCollection, RorId
from domain.structures.name_forms import StructureNameForm


class StructureType(StrEnum):
    """Type d'une structure de recherche / d'enseignement.

    Mappe sur l'enum Postgres `structure_type`. `StrEnum` (PEP 663) garde
    la valeur sérialisable telle quelle vers SQL et API.
    """

    UNIVERSITE = "universite"
    CHU = "chu"
    ECOLE = "ecole"
    LABO = "labo"
    EQUIPE = "equipe"
    SITE = "site"
    ONR = "onr"
    # Structure administrative : service (direction des systèmes d'information, bibliothèque
    # universitaire) ou structure fédérative intermédiaire (institut, sous tutelle de l'université
    # et tutelle de laboratoires).
    ADMIN = "admin"
    AUTRE = "autre"


@dataclass(slots=True)
class Structure:
    """Structure de recherche / d'enseignement (aggregate root)."""

    id: int | None
    code: str
    name: str
    structure_type: StructureType
    acronym: str | None = None
    ror_id: RorId | None = None
    hal_collection: HalCollection | None = None
    api_ids: dict[str, list[str]] | None = None
    name_forms: tuple[StructureNameForm, ...] = field(default=())
