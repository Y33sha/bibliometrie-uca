"""Port : lectures sur les contributions sources (consommé par le router contributions).

Implémenté par `infrastructure.read_models.contributions.PgContributionsQueries`. La file des contributions sources orphelines lit `source_contributions`, un cran sous les contributions : elle appartient donc aux contributions, et non aux personnes qu'elle sert à rattacher.
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
    """Laboratoires du périmètre détectés dans les adresses de la contribution source."""


class OrphanContributionsResponse(PaginatedResponse):
    contributions: list[OrphanContributionOut]


@dataclass(frozen=True, slots=True)
class OrphanFilters:
    """Filtres de la file des contributions sources orphelines.

    `search` vise le nom de la contribution source. `lab_ids` et `lab_none` se combinent en OU : contributions sources dont les adresses désignent l'un des laboratoires, ou aucun laboratoire. Vides, ils laissent tout passer.
    """

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False


class OrphanContributionsFacetsResponse(BaseModel):
    """Facette laboratoires de la file des contributions sources orphelines : décompte par laboratoire détecté dans la contribution source, et nombre de contributions sources sans laboratoire."""

    labs: list[FacetOption]
    no_lab_count: int


class ContributionsQueries(Protocol):
    """Lectures sync pour `/api/contributions/*`."""

    def orphan_contributions_count(self) -> OrphanCountResponse:
        """Nombre de contributions sources du périmètre rattachées à aucune personne."""
        ...

    def list_orphan_contributions(
        self, *, filters: OrphanFilters, page: int, per_page: int
    ) -> OrphanContributionsResponse:
        """Liste paginée des contributions sources orphelines, avec leur publication."""
        ...

    def orphan_contributions_facets(
        self, *, filters: OrphanFilters
    ) -> OrphanContributionsFacetsResponse:
        """Facette laboratoires des contributions sources orphelines. Le filtre de recherche s'applique ; le filtre laboratoires, objet de la facette, ne s'applique pas."""
        ...
