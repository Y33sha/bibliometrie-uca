"""Modèles de réponse : lectures pour /api/hal-problems/*."""

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from domain.sources.registry import Source, source_record_url
from infrastructure.read_models._common import (
    PaginatedResponse,
    SourceLink,
    StructureRef,
    hal_links,
)


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
    """Métadonnées et dépôts HAL d'une publication, communs aux listes de doublons HAL."""

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
    """Laboratoire doté d'une collection HAL, pour le sélecteur des manques de collection."""

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
    """Raison pour laquelle la question « que manque-t-il à sa collection ? » reste sans réponse pour ce laboratoire : laboratoire inexistant, ou laboratoire réel sans collection HAL configurée."""

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
    """Laboratoires du périmètre de la publication ; l'affichage choisit entre acronyme et nom."""

    @computed_field
    @property
    def hal_links(self) -> list[SourceLink]:
        """Dépôts HAL de la publication, avec leur lien."""
        return hal_links(self.halids)


class HalAffiliationConflictsResponse(PaginatedResponse):
    publications: list[HalAffiliationConflictPublication]


class HalAccountSummary(BaseModel):
    hal_person_id: int
    full_name: str | None
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
