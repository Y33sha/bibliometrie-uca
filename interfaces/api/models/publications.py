"""Modèles Pydantic pour les publications (liste, détail, facettes)."""

from pydantic import BaseModel

from interfaces.api.models._common import YesNoCount
from interfaces.api.models.subjects import SubjectOut

# ----- Entrées (POST/PUT/PATCH) -----


class MergePublications(BaseModel):
    target_id: int
    source_id: int


class MarkDistinctPublications(BaseModel):
    pub_id_a: int
    pub_id_b: int


class ExcludeSourceAuthorship(BaseModel):
    excluded: bool = True


# ----- Listing -----


class PubLabItem(BaseModel):
    id: int
    label: str


class PubApcPayment(BaseModel):
    """Détail d'un paiement APC (une ligne d'`apc` dans la liste)."""

    amount: float
    institution: str | None
    lab_id: int | None
    lab_acronym: str | None
    budget_structure_id: int | None


class PublicationListItem(BaseModel):
    """Ligne de `/api/publications` (liste + recherche)."""

    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    oa_status: str
    journal: str | None
    publisher: str | None
    hal_id: str | None
    openalex_id: str | None
    scanr_id: str | None
    wos_id: str | None
    theses_id: str | None
    date_soutenance: str | None
    date_inscription: str | None
    labs: str | None
    lab_items: list[PubLabItem] | None
    apc: list[PubApcPayment] | None
    is_corresponding: bool | None
    authorship_id: int | None
    hal_collections: list[str] | None


class PublicationListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    publications: list[PublicationListItem]


# ----- Facettes -----


class IntValueFacet(BaseModel):
    value: int
    count: int


class StrValueFacet(BaseModel):
    value: str
    count: int


class LabeledIntFacet(BaseModel):
    value: int
    label: str
    count: int


class TextStrFacet(BaseModel):
    value: str
    text: str
    count: int


class PublicationsFacetsResponse(BaseModel):
    """Facettes dynamiques pour la page publications.

    Chaque facette exclut son propre filtre mais applique tous les
    autres. `hal_status` est vide tant qu'un labo unique n'est pas
    sélectionné. `corresponding`, `in_perimeter` sont vides sans
    `person_id`.
    """

    years: list[IntValueFacet]
    labs: list[LabeledIntFacet]
    no_lab_count: int
    doc_types: list[StrValueFacet]
    access: list[TextStrFacet]
    oa_statuses: list[StrValueFacet]
    corresponding: list[StrValueFacet]
    source_counts: dict[str, YesNoCount]
    apc: list[TextStrFacet]
    countries: list[TextStrFacet]
    hal_status: list[TextStrFacet]
    in_perimeter: list[TextStrFacet]


# ----- Détail publication -----


class PublicationDetailCore(BaseModel):
    """Métadonnées de la publication (bloc `publication` du détail)."""

    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    oa_status: str
    language: str | None
    container_title: str | None
    abstract: str | None
    journal_id: int | None
    journal_title: str | None
    issn: str | None
    eissn: str | None
    journal_predatory: bool | None
    apc_amount: float | None
    apc_currency: str | None
    oa_model: str | None
    publisher_id: int | None
    publisher_name: str | None
    publisher_predatory: bool | None


class SourcePublicationOut(BaseModel):
    source: str
    source_id: str
    doi: str | None
    hal_collections: list[str] | None
    countries: list[str] | None


class ConsolidatedAuthorshipOut(BaseModel):
    """Authorship consolidée (liens certifiés person ↔ publication)."""

    author_position: int | None
    in_perimeter: bool
    is_corresponding: bool | None
    structure_ids: list[int] | None
    source_hal: bool
    source_openalex: bool
    source_wos: bool
    source_scanr: bool
    person_id: int
    last_name: str
    first_name: str


class SourceAuthorshipOut(BaseModel):
    """Authorship source (HAL / OpenAlex / WoS / ScanR).

    `raw_affiliation` agrège les adresses brutes liées à l'authorship via
    `source_authorship_addresses` ; `None` s'il n'y en a pas.
    """

    id: int
    author_position: int | None
    full_name: str | None
    person_id: int | None
    in_perimeter: bool
    structure_ids: list[int] | None
    raw_affiliation: str | None = None
    excluded: bool
    countries: list[str] | None


class ThesesAuthorshipOut(BaseModel):
    id: int
    author_position: int | None
    full_name: str | None
    person_id: int | None
    roles: list[str]
    in_perimeter: bool


class EcoleDoctorale(BaseModel):
    nom: str
    ppn: str | None = None


class PartenaireThese(BaseModel):
    nom: str
    type: str | None = None


class ThesisMeta(BaseModel):
    discipline: str | None
    ecoles_doctorales: list[EcoleDoctorale] | None
    partenaires: list[PartenaireThese] | None
    date_soutenance: str | None
    date_inscription: str | None


class StructureInfo(BaseModel):
    acronym: str | None
    name: str
    type: str


class PublicationDetailResponse(BaseModel):
    """Détail complet d'une publication : métadonnées + sources + authorships."""

    publication: PublicationDetailCore
    sources: list[SourcePublicationOut]
    authorships: list[ConsolidatedAuthorshipOut]
    hal_authorships: list[SourceAuthorshipOut]
    openalex_authorships: list[SourceAuthorshipOut]
    wos_authorships: list[SourceAuthorshipOut]
    scanr_authorships: list[SourceAuthorshipOut]
    theses_authorships: list[ThesesAuthorshipOut]
    thesis_meta: ThesisMeta | None
    structures: dict[str, StructureInfo]
    subjects: list[SubjectOut]


class ExcludeSourceAuthorshipResponse(BaseModel):
    ok: bool
    excluded: bool
