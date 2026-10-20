"""Port : lectures sur les signatures (consommé par le router contributions).

Implémenté par `infrastructure.read_models.contributions.PgContributionsQueries`. La file des signatures orphelines lit `source_contributions` un cran sous les signatures consolidées : elle appartient donc aux contributions, non aux personnes qu'elle sert à rattacher.
"""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from application.ports.read_models._common import FacetOption, PaginatedResponse
from application.ports.read_models.publications_queries import PublicationLabItem


class OrphanCountResponse(BaseModel):
    total: int


class OrphanContributionOut(BaseModel):
    source: str
    source_contribution_id: int
    full_name: str
    last_name: str
    first_name: str
    publication_id: int
    publication_title: str
    publication_year: int | None
    labs: list[PublicationLabItem]
    """Laboratoires du périmètre détectés dans les adresses de la signature."""


class OrphanContributionsResponse(PaginatedResponse):
    contributions: list[OrphanContributionOut]


@dataclass(frozen=True, slots=True)
class OrphanFilters:
    """Filtres de la file des signatures orphelines.

    `search` porte sur le nom de la signature. `lab_ids` et `lab_none` se combinent en OU : signatures dont les adresses désignent l'un des laboratoires, ou aucun laboratoire. Vides, ils laissent tout passer.
    """

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False


class OrphanContributionsFacetsResponse(BaseModel):
    """Facette laboratoires de la file des signatures orphelines : décompte par laboratoire détecté dans la signature, et nombre de signatures sans laboratoire."""

    labs: list[FacetOption]
    no_lab_count: int


class ContributionsQueries(Protocol):
    """Lectures sync pour `/api/contributions/*`."""

    def orphan_contributions_count(self) -> OrphanCountResponse:
        """Nombre de signatures du périmètre qu'aucune personne ne porte."""
        ...

    def list_orphan_contributions(
        self, *, filters: OrphanFilters, page: int, per_page: int
    ) -> OrphanContributionsResponse:
        """Liste paginée des signatures orphelines, avec la publication qu'elles signent."""
        ...

    def orphan_contributions_facets(
        self, *, filters: OrphanFilters
    ) -> OrphanContributionsFacetsResponse:
        """Facette laboratoires des signatures orphelines. Le filtre de recherche s'applique ; le filtre laboratoires, objet de la facette, ne s'applique pas."""
        ...
