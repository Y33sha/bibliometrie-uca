"""Port : lectures sur les sujets (consommé par le router subjects).

Implémenté par `infrastructure.queries.api.subjects.PgSubjectsQueries`. Les écritures du référentiel, faites par la phase d'ingestion, passent par `application.ports.pipeline.subjects.SubjectsIngestionQueries`.

`SubjectFrequency` vit ici et sert les quatre nuages de sujets des ports voisins : personnes, laboratoires, revues et éditeurs.
"""

from typing import Protocol

from pydantic import BaseModel

from application.ports.api._common import PaginatedResponse


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


class SubjectDetailResponse(BaseModel):
    """Détail d'un sujet et ses voisins par co-occurrence."""

    subject: SubjectListItem
    neighbors: list[SubjectNeighborOut]


class SubjectFrequency(BaseModel):
    """Sujet et son nombre de publications au sein d'une entité donnée — personne, laboratoire, revue ou éditeur. Alimente les nuages de sujets de leurs pages de détail."""

    id: int
    label: str
    count: int


class SubjectsQueries(Protocol):
    """Lectures sur les sujets (annuaire, voisins par co-occurrence)."""

    def list_subjects(
        self, *, q: str | None, limit: int, offset: int, min_usage_count: int
    ) -> list[SubjectListItem]: ...

    def count_subjects(self, *, q: str | None, min_usage_count: int) -> int: ...

    def get_subject(self, subject_id: int) -> SubjectListItem | None: ...

    def get_subject_neighbors(
        self, subject_id: int, *, limit: int, min_cooccurrence_count: int
    ) -> list[SubjectNeighborOut]: ...
