"""Port : lectures pour /api/hal-problems/*.

Implémenté par `infrastructure.read_models.hal_problems.PgHalProblemsQueries`.

Placement par cas d'usage (le seul appelant est le router de diagnostics HAL), pas par table.
"""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, computed_field

from application.ports.read_models._common import (
    PaginatedResponse,
    SourceLink,
    StructureRef,
    hal_links,
)
from domain.sources.registry import Source, source_record_url


class HalDocSummary(BaseModel):
    """Détail d'un dépôt HAL rattaché à une publication."""

    halid: str
    hal_collections: list[str] | None
    hal_doc_type: str | None
    hal_publication_year: int | None
    hal_title: str | None
    author_count: int

    @computed_field
    @property
    def record_url(self) -> str:
        """Lien vers le dépôt sur HAL."""
        return source_record_url(Source.HAL, self.halid)


class HalPublicationDetail(BaseModel):
    """Métadonnées + dépôts HAL d'une publication (commun aux doublons HAL)."""

    id: int
    title: str
    publication_year: int | None
    doc_type: str
    doi: str | None
    container_title: str | None
    hal_docs: list[HalDocSummary]


class HalDoiDuplicatePair(BaseModel):
    doi: str
    halids: list[str]
    publication: HalPublicationDetail


class HalDoiDuplicatesResponse(PaginatedResponse):
    pairs: list[HalDoiDuplicatePair]


class HalMetaDuplicatePair(BaseModel):
    publication_a: HalPublicationDetail
    publication_b: HalPublicationDetail


class HalMetaDuplicatesResponse(PaginatedResponse):
    pairs: list[HalMetaDuplicatePair]


class HalCollectionLab(BaseModel):
    """Labo configuré avec une collection HAL (sélecteur missing-collections)."""

    id: int
    acronym: str | None
    name: str
    hal_collection: str


class HalMissingCollectionPublication(BaseModel):
    id: int
    title: str
    publication_year: int | None
    doc_type: str
    doi: str | None
    halids: list[str] | None = Field(exclude=True)
    outside_perimeter_collections: bool
    """Le dépôt HAL ne figure dans aucune collection des structures racines du périmètre : il a été trouvé par la collection d'un autre laboratoire, non par celle de l'établissement."""

    @computed_field
    @property
    def hal_links(self) -> list[SourceLink]:
        """Dépôts HAL de la publication, avec leur lien."""
        return hal_links(self.halids)


class HalMissingCollectionsResponse(PaginatedResponse):
    lab_acronym: str | None
    hal_collection: str
    publications: list[HalMissingCollectionPublication]


class NoMissingCollections(StrEnum):
    """Pourquoi la question « que manque-t-il à sa collection ? » n'a pas de réponse pour ce laboratoire.

    Les deux cas se distinguent parce qu'ils tiennent à des choses différentes : l'un désigne un laboratoire qui n'existe pas, l'autre un laboratoire réel dont aucune collection HAL n'est configurée.
    """

    UNKNOWN_LAB = "unknown_lab"
    NO_COLLECTION = "no_collection"


class HalAffiliationConflictPublication(BaseModel):
    id: int
    title: str
    publication_year: int | None
    doc_type: str
    doi: str | None
    halids: list[str] | None = Field(exclude=True)
    laboratories: list[StructureRef]
    """Laboratoires du périmètre que la publication porte ; l'affichage choisit entre acronyme et nom."""

    @computed_field
    @property
    def hal_links(self) -> list[SourceLink]:
        """Dépôts HAL de la publication, avec leur lien."""
        return hal_links(self.halids)


class HalAffiliationConflictsResponse(PaginatedResponse):
    publications: list[HalAffiliationConflictPublication]


class HalAccountSummary(BaseModel):
    hal_person_id: int
    full_name: str
    idhal: str | None
    orcid: str | None
    idref: str | None
    publication_count: int


class HalDuplicateAccountPerson(BaseModel):
    person_id: int
    last_name: str
    first_name: str
    has_rh: bool
    hal_accounts: list[HalAccountSummary]


class HalDuplicateAccountsResponse(PaginatedResponse):
    persons: list[HalDuplicateAccountPerson]


class HalProblemsQueries(Protocol):
    """Lectures de diagnostic qualité HAL."""

    def hal_duplicate_accounts(
        self, *, page: int, per_page: int
    ) -> HalDuplicateAccountsResponse: ...

    def hal_duplicate_publications_by_doi(
        self, *, page: int, per_page: int
    ) -> HalDoiDuplicatesResponse: ...

    def hal_duplicate_publications_by_metadata(
        self, *, page: int, per_page: int
    ) -> HalMetaDuplicatesResponse: ...

    def hal_missing_collections_labs(self) -> list[HalCollectionLab]: ...

    def hal_missing_collections(
        self, *, lab_id: int, page: int, per_page: int
    ) -> HalMissingCollectionsResponse | NoMissingCollections: ...

    def hal_affiliation_conflicts(
        self, *, page: int, per_page: int
    ) -> HalAffiliationConflictsResponse: ...
