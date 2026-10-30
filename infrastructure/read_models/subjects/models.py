"""Modèles de réponse : lectures sur les sujets.

Les écritures du référentiel appartiennent à la phase `subjects` (`pipeline/transformation/publications/subjects/subject_store.py`).

`SubjectFrequency` sert aussi les nuages de sujets des personnes, des laboratoires, des revues et des éditeurs.
"""

from pydantic import BaseModel

from infrastructure.read_models._common import PaginatedResponse


class SubjectOut(BaseModel):
    """Sujet attaché à une publication, une ligne par sujet toutes sources réunies."""

    id: int
    label: str
    language: str | None
    sources: list[str]
    """Sources ayant fourni le sujet."""


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
    """Sujet et son nombre de publications au sein d'une personne, d'un laboratoire, d'une revue ou d'un éditeur, pour les sujets principaux de son tableau de bord."""

    id: int
    label: str
    count: int
