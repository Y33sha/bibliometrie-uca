"""Modèles Pydantic pour le tableau de bord des problèmes HAL."""

from pydantic import BaseModel


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


class HalDoiDuplicatesResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    pairs: list[HalDoiDuplicatePair]


class HalMetaDuplicatePair(BaseModel):
    pub_a: HalPubDetail
    pub_b: HalPubDetail


class HalMetaDuplicatesResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
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
    hors_uca: bool


class HalMissingCollectionsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    lab_acronym: str | None
    hal_collection: str
    publications: list[HalMissingCollectionPub]


class HalAffiliationConflictPub(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doc_type: str
    doi: str | None
    halids: list[str] | None
    labs: str | None


class HalAffiliationConflictsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
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


class HalDuplicateAccountsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    persons: list[HalDuplicateAccountPerson]
