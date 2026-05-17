"""Port : lectures sur les sujets (consommé par le router subjects).

Implémenté par `infrastructure.queries.subjects.PgSubjectsAdminQueries`.

Note : `application.ports.subjects.SubjectsQueries` couvre la variante utilisée par le pipeline de normalisation (upsert/link/cleanup). Ce port-ci ne couvre que les lectures de l'API admin.

Co-localise les DTOs Pydantic retournés par ce port + `SubjectFrequency`, utilisé par les ports voisins (`persons_queries.person_subjects`, `laboratories_queries.lab_subjects`). Cf. chantier `CODE_typage-projections-strict` Phase 4 — les DTOs vivent dans le port qui les définit (zone neutre, à côté des Protocols et dataclasses de filtres).
"""

from typing import Protocol

from pydantic import BaseModel


class SubjectOntologyEntry(BaseModel):
    """Annotation d'un sujet par une ontologie donnée :
    - `codes` : codes intra-ontologie observés (ex 'info' pour HAL).
    - `level` : niveau hiérarchique (0=racine), null si non applicable.
    - `parent` : libellé du sujet parent dans la même ontologie, null si racine.
    """

    codes: list[str]
    level: int | None = None
    parent: str | None = None


class SubjectOut(BaseModel):
    """Sujet attaché à une publication, agrégé par `subject_id` sur les différentes sources qui l'ont annoté.

    `ontologies` : annotations multi-sources. Vide pour un libre.
    """

    id: int
    label: str
    language: str | None
    ontologies: dict[str, SubjectOntologyEntry]
    sources: list[str]  # publications sources qui ont annoté ce sujet


class SubjectListItem(BaseModel):
    """Sujet dans une liste paginée (page `/subjects`)."""

    id: int
    label: str
    language: str | None
    ontologies: dict[str, SubjectOntologyEntry]
    usage_count: int


class SubjectListResponse(BaseModel):
    items: list[SubjectListItem]
    total: int
    page: int
    per_page: int


class SubjectNeighborOut(BaseModel):
    """Voisin d'un sujet par co-occurrence."""

    id: int
    label: str
    ontologies: dict[str, SubjectOntologyEntry]
    usage_count: int
    cooccurrence_count: int


class SubjectDetailResponse(BaseModel):
    """Détail d'un sujet + ses voisins par co-occurrence (page graphe)."""

    subject: SubjectListItem
    neighbors: list[SubjectNeighborOut]


class SubjectFrequency(BaseModel):
    """Sujet avec fréquence locale (count des publis du contexte parent : labo ou personne). Utilisé pour les nuages de mots. Retourné par `PersonsQueries.person_subjects` et `LaboratoriesQueries.lab_subjects`."""

    id: int
    label: str
    ontologies: dict[str, SubjectOntologyEntry]
    count: int


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
