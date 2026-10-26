"""Modèles de réponse : lectures sur les contributions.

La file des contributions orphelines lit les groupes de contributions sources du périmètre rattachés à aucune personne.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel

from infrastructure.read_models._common import FacetOption, PaginatedResponse
from infrastructure.read_models.publications.models import PublicationLabItem


class OrphanCountResponse(BaseModel):
    total: int


class OrphanContributionOut(BaseModel):
    """Contribution orpheline : groupe de contributions sources du périmètre, sous un rôle d'auteur, rattaché à aucune personne."""

    contribution_id: int
    sources: list[str]
    """Sources des membres du groupe, sans doublon, par ordre de priorité."""
    full_name: str
    """Nom du membre de la source la plus prioritaire."""
    last_name: str
    first_name: str
    publication_id: int
    publication_title: str
    publication_year: int | None
    labs: list[PublicationLabItem]
    """Laboratoires du périmètre détectés dans les adresses des membres du groupe."""


class OrphanContributionsResponse(PaginatedResponse):
    contributions: list[OrphanContributionOut]


@dataclass(frozen=True, slots=True)
class OrphanFilters:
    """Filtres de la file des contributions orphelines.

    `search` vise le nom des membres du groupe. `lab_ids` et `lab_none` se combinent en OU : groupes dont les adresses des membres désignent l'un des laboratoires, ou aucun laboratoire. Vides, ils laissent tout passer.
    """

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False


class OrphanContributionsFacetsResponse(BaseModel):
    """Facette laboratoires de la file des contributions orphelines : décompte par laboratoire détecté dans les membres du groupe, et nombre de groupes sans laboratoire."""

    labs: list[FacetOption]
    no_lab_count: int
