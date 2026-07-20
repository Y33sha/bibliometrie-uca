"""Port : lectures pour /api/hal-problems/*.

Implémenté par `infrastructure.queries.api.hal_problems.PgHalProblemsQueries`.

Placement par cas d'usage (le seul appelant est le router de diagnostics HAL), pas par table.

Les modèles Pydantic que ces lectures rendent sont co-localisés ici : leur contrat appartient au port.
"""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from application.ports.api._common import PaginatedResponse, StructureRef


class HalDocSummary(BaseModel):
    """Détail d'un dépôt HAL rattaché à une publication."""

    halid: str
    hal_collections: list[str] | None
    hal_doc_type: str | None
    hal_pub_year: int | None
    hal_title: str | None
    author_count: int


class HalPubDetail(BaseModel):
    """Métadonnées + dépôts HAL d'une publication (commun aux doublons HAL)."""

    id: int
    title: str
    pub_year: int | None
    doc_type: str
    doi: str | None
    container_title: str | None
    hal_docs: list[HalDocSummary]


class HalDoiDuplicatePair(BaseModel):
    doi: str
    halids: list[str]
    publication: HalPubDetail


class HalDoiDuplicatesResponse(PaginatedResponse):
    pairs: list[HalDoiDuplicatePair]


class HalMetaDuplicatePair(BaseModel):
    pub_a: HalPubDetail
    pub_b: HalPubDetail


class HalMetaDuplicatesResponse(PaginatedResponse):
    pairs: list[HalMetaDuplicatePair]


class HalCollectionLab(BaseModel):
    """Labo configuré avec une collection HAL (sélecteur missing-collections)."""

    id: int
    acronym: str | None
    name: str
    hal_collection: str


class HalMissingCollectionPub(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doc_type: str
    doi: str | None
    halids: list[str] | None
    outside_perimeter_collections: bool
    """Le dépôt HAL ne figure dans aucune collection des structures racines du périmètre : il a été trouvé par la collection d'un autre laboratoire, non par celle de l'établissement."""


class HalMissingCollectionsResponse(PaginatedResponse):
    lab_acronym: str | None
    hal_collection: str
    publications: list[HalMissingCollectionPub]


class NoMissingCollections(StrEnum):
    """Pourquoi la question « que manque-t-il à sa collection ? » n'a pas de réponse pour ce laboratoire.

    Les deux cas se distinguent parce qu'ils tiennent à des choses différentes : l'un désigne un laboratoire qui n'existe pas, l'autre un laboratoire réel dont aucune collection HAL n'est configurée.
    """

    UNKNOWN_LAB = "unknown_lab"
    NO_COLLECTION = "no_collection"


class HalAffiliationConflictPub(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doc_type: str
    doi: str | None
    halids: list[str] | None
    laboratories: list[StructureRef]
    """Laboratoires du périmètre que la publication porte ; l'affichage choisit entre acronyme et nom."""


class HalAffiliationConflictsResponse(PaginatedResponse):
    publications: list[HalAffiliationConflictPub]


class HalAccountSummary(BaseModel):
    hal_person_id: int
    full_name: str
    idhal: str | None
    orcid: str | None
    idref: str | None
    pub_count: int


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

    def hal_duplicate_pubs_by_doi(
        self, *, page: int, per_page: int
    ) -> HalDoiDuplicatesResponse: ...

    def hal_duplicate_pubs_by_metadata(
        self, *, page: int, per_page: int
    ) -> HalMetaDuplicatesResponse: ...

    def hal_missing_collections_labs(self) -> list[HalCollectionLab]: ...

    def hal_missing_collections(
        self, *, lab_id: int, page: int, per_page: int
    ) -> HalMissingCollectionsResponse | NoMissingCollections: ...

    def hal_affiliation_conflicts(
        self, *, page: int, per_page: int
    ) -> HalAffiliationConflictsResponse: ...
