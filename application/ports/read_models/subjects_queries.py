"""Port : lectures sur les sujets.

Implémenté par `infrastructure.read_models.subjects.PgSubjectsQueries`. Les écritures du référentiel appartiennent à la phase `subjects` (`pipeline/transformation/publications/subjects/subjects_queries.py`).

`SubjectFrequency` vit ici et sert les quatre nuages de sujets des ports voisins : personnes, laboratoires, revues et éditeurs.
"""

from typing import Protocol

from pydantic import BaseModel

from application.ports.read_models._common import PaginatedResponse


class SubjectOut(BaseModel):
    """Sujet attaché à une publication. Les annotations des différentes sources sont agrégées en une ligne par sujet, `sources` retenant celles qui l'ont fourni."""

    id: int
    label: str
    language: str | None
    sources: list[str]


class SubjectListItem(BaseModel):
    """Sujet du référentiel et son nombre de publications, servi en liste comme en détail."""

    id: int
    label: str
    language: str | None
    usage_count: int


class SubjectListResponse(PaginatedResponse):
    items: list[SubjectListItem]


class SubjectNeighborOut(BaseModel):
    """Voisin d'un sujet par co-occurrence."""

    id: int
    label: str
    usage_count: int
    cooccurrence_count: int


class SubjectNeighborLink(BaseModel):
    """Co-occurrence entre deux voisins d'un sujet, `subject_a_id` < `subject_b_id`."""

    subject_a_id: int
    subject_b_id: int
    cooccurrence_count: int


class SubjectDetailResponse(BaseModel):
    """Détail d'un sujet, ses voisins par co-occurrence et les co-occurrences entre ces voisins."""

    subject: SubjectListItem
    neighbors: list[SubjectNeighborOut]
    neighbor_links: list[SubjectNeighborLink]


class SubjectFrequency(BaseModel):
    """Sujet et son nombre de publications au sein d'une entité donnée — personne, laboratoire, revue ou éditeur. Alimente les sujets principaux de leurs dashboards."""

    id: int
    label: str
    count: int


class SubjectsQueries(Protocol):
    """Lectures sur les sujets (annuaire, voisins par co-occurrence)."""

    def list_subjects(
        self, *, search: str | None, page: int, per_page: int, min_usage_count: int
    ) -> SubjectListResponse: ...

    def get_subject_detail(
        self, subject_id: int, *, neighbors_limit: int, min_cooccurrence_count: int
    ) -> SubjectDetailResponse | None: ...
