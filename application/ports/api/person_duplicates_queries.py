"""Port : lectures pour /api/admin/person-duplicates/*.

Implémenté par `infrastructure.queries.api.person_duplicates.PgPersonDuplicatesQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4.
"""

from typing import Protocol

from pydantic import BaseModel


def parse_skip_pairs(skip: str) -> set[tuple[int, int]]:
    """Parse 'idA-idB,idA-idB,...' en set de tuples (helper pur)."""
    result: set[tuple[int, int]] = set()
    if skip:
        for s in skip.split(","):
            parts = s.strip().split("-")
            if len(parts) == 2:
                try:
                    result.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    pass
    return result


class PersonDedupIdentifier(BaseModel):
    id: int
    id_type: str
    id_value: str
    source: str
    status: str


class PersonDedupPublication(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    sources: list[str]


class PersonDedupLab(BaseModel):
    id: int
    acronym: str | None
    name: str


class PersonDedupDetail(BaseModel):
    """Profil d'une personne pour la page de déduplication."""

    id: int
    last_name: str
    first_name: str
    last_name_normalized: str
    first_name_normalized: str
    has_rh: bool
    role_title: str | None
    department_name: str | None
    identifiers: list[PersonDedupIdentifier]
    publications: list[PersonDedupPublication]
    pub_count: int
    labs: list[PersonDedupLab]


class PersonDuplicatePair(BaseModel):
    person_a: PersonDedupDetail
    person_b: PersonDedupDetail


class PersonConflictPub(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doc_type: str
    position: int


class PersonConflictPair(BaseModel):
    person_a: PersonDedupDetail
    person_b: PersonDedupDetail
    conflict_pubs: list[PersonConflictPub]


class PersonDuplicatesQueries(Protocol):
    """Lectures sur les doublons personnes (candidats + conflits co-auteurs)."""

    def count_person_duplicates(self) -> int: ...

    def next_person_duplicate(
        self, *, skip_pairs: set[tuple[int, int]] | None, offset: int
    ) -> PersonDuplicatePair | None: ...

    def count_person_conflict_pairs(self) -> int: ...

    def next_person_conflict(
        self, *, skip_pairs: set[tuple[int, int]], offset: int
    ) -> PersonConflictPair | None: ...
