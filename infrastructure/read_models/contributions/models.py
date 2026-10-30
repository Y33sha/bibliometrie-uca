"""Modèles de réponse : lectures sur les contributions."""

from dataclasses import dataclass, field

from application.ports.model import Model
from infrastructure.read_models._common import FacetOption, PaginatedResponse
from infrastructure.read_models.publications.models import PublicationLabItem


class OrphanCountResponse(Model):
    total: int


class OrphanContributionOut(Model):
    """Contribution orpheline : contribution du périmètre, sous un rôle d'auteur, rattachée à aucune personne."""

    contribution_id: int
    sources: list[str]
    """Sources des contributions sources de la contribution, sans doublon, par ordre de priorité."""
    full_name: str
    """Nom de la contribution source de la source la plus prioritaire."""
    last_name: str
    first_name: str
    publication_id: int
    publication_title: str
    publication_year: int | None
    labs: list[PublicationLabItem]
    """Laboratoires du périmètre détectés dans les adresses des contributions sources de la contribution."""


class OrphanContributionsResponse(PaginatedResponse):
    contributions: list[OrphanContributionOut]


@dataclass(frozen=True, slots=True)
class OrphanFilters:
    """Filtres de la file des contributions orphelines.

    `lab_ids` et `lab_none` se combinent en OU. Vides, ils laissent tout passer.
    """

    search: str = ""
    """Terme cherché dans le nom des contributions sources de la contribution."""
    lab_ids: list[int] = field(default_factory=list)
    """Laboratoires désignés par les adresses des contributions sources."""
    lab_none: bool = False
    """Retient les contributions sans laboratoire."""


class OrphanContributionsFacetsResponse(Model):
    """Facette laboratoires de la file des contributions orphelines."""

    labs: list[FacetOption]
    """Décompte par laboratoire détecté dans les contributions sources de la contribution."""
    no_lab_count: int
    """Nombre de contributions sans laboratoire."""
