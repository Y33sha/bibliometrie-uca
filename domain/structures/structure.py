"""Aggregate root `Structure` — entité métier d'une structure de recherche / d'enseignement (laboratoire, école doctorale, université, hôpital, …).

Identité = `id` (clé surrogate) ; identifiant naturel : `code` (unique). Une structure agrège ses formes de noms (`name_forms`), ses identifiants externes (`RorId`, `HalCollection`) et un dict `api_ids` JSONB pour les identifiants de sources sans VO dédié (clés : `openalex`, `wos`, `scanr`, `theses`, `hal`).

Les règles métier des structures (matching des formes de nom, hiérarchie `structure_relations`) vivent dans les modules voisins du package `domain/structures/`.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from domain.structures.identifiers import HalCollection, RorId
from domain.structures.name_forms import StructureNameForm


class StructureType(StrEnum):
    """Type d'une structure de recherche / d'enseignement.

    Mappe sur l'enum Postgres `structure_type`. `StrEnum` garde la valeur sérialisable telle quelle vers SQL et API.
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

    @property
    def is_affiliation(self) -> bool:
        """Vrai si un rattachement à une structure de ce type constitue une affiliation.

        Un site porte les formes de nom d'un lieu — communes, campus, codes postaux — pour servir de contexte de reconnaissance à d'autres structures, via `structure_name_forms.requires_context_of`. Une adresse qui le mentionne atteste d'un lieu, non d'un rattachement institutionnel : le site est un instrument du matching, jamais son résultat.
        """
        return self is not StructureType.SITE


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
