"""Port : lectures sur les sujets (consommé par le router subjects).

Implémenté par
`infrastructure.queries.subjects.PgSubjectsAdminQueries`.

Note : `application.ports.subjects.SubjectsQueries` couvre la variante
utilisée par le pipeline de normalisation (upsert/link/cleanup).
Ce port-ci ne couvre que les lectures de l'API admin.
"""

from typing import Protocol

from application.subjects.dtos import SubjectListItem, SubjectNeighborOut


class SubjectsAdminQueries(Protocol):
    """Lectures sur les sujets (annuaire, voisins par co-occurrence)."""

    def list_subjects(
        self, *, q: str | None, limit: int, offset: int, min_count: int
    ) -> list[SubjectListItem]: ...

    def count_subjects(self, *, q: str | None, min_count: int) -> int: ...

    def get_subject(self, subject_id: int) -> SubjectListItem | None: ...

    def get_subject_neighbors(
        self, subject_id: int, *, limit: int, min_count: int
    ) -> list[SubjectNeighborOut]: ...
