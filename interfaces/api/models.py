"""Pydantic models shared across routers."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

# ----- Auth -----


class LoginRequest(BaseModel):
    username: str
    password: str


# ----- Addresses -----


class ReviewAction(BaseModel):
    structure_id: int
    is_confirmed: bool | None  # True = confirmé, False = rejeté, None = reset


class BatchReviewAction(BaseModel):
    address_ids: list[int]
    structure_id: int
    is_confirmed: bool | None


class AssignStructureAction(BaseModel):
    structure_id: int


class SetCountry(BaseModel):
    countries: list[str] | None = None


class BatchSetCountry(BaseModel):
    country_code: str
    address_ids: list[int] | None = None
    search: str = ""
    has_country: str = ""
    country_code_filter: str = ""
    suggested_country: str = ""


# ----- Structures -----


class StructureCreate(BaseModel):
    code: str
    name: str
    acronym: str | None = None
    type: str
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict | None = None


class StructureUpdate(BaseModel):
    name: str | None = None
    acronym: str | None = None
    type: str | None = None
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict | None = None


class RelationCreate(BaseModel):
    parent_id: int
    child_id: int
    relation_type: str


class NameFormCreate(BaseModel):
    structure_id: int
    form_text: str
    is_word_boundary: bool = False
    is_excluding: bool = False
    requires_context_of: list[int] | None = None


class NameFormUpdate(BaseModel):
    form_text: str | None = None
    is_word_boundary: bool | None = None
    is_excluding: bool | None = None
    requires_context_of: list[int] | None = None


# ----- Structures (output) -----


class StructureListItem(BaseModel):
    """Ligne résumée de `/api/structures` (liste + recherche)."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str


class StructureOut(BaseModel):
    """Structure complète — renvoyée par GET/POST/PUT sur `/api/structures`."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, list[str]] | None


class RelatedStructureOut(BaseModel):
    """Structure voisine (parent/enfant) dans le détail d'une structure."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    relation_id: int
    relation_type: str


class NameFormOut(BaseModel):
    """Forme de nom d'une structure."""

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None
    created_at: datetime | None = None


class StructureDetailResponse(BaseModel):
    """Détail complet renvoyé par GET /api/structures/{id}."""

    structure: StructureOut
    parents: list[RelatedStructureOut]
    children: list[RelatedStructureOut]
    forms: list[NameFormOut]


class StructureRelationOut(BaseModel):
    """Relation structure-à-structure."""

    id: int
    parent_id: int
    child_id: int
    relation_type: str


class StructureRelationCreateResponse(BaseModel):
    """Réponse de POST /api/structure-relations.

    Polymorphe : soit la relation créée, soit `{status: "already_exists"}`.
    """

    id: int | None = None
    parent_id: int | None = None
    child_id: int | None = None
    relation_type: str | None = None
    status: str | None = None


class DeletedResponse(BaseModel):
    deleted: bool = True


# ----- Journals / Publishers -----


class JournalUpdate(BaseModel):
    title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    doi_prefix: str | None = None
    oa_model: str | None = None
    journal_type: str | None = None
    is_academic: bool | None = None
    is_predatory: bool | None = None
    is_in_doaj: bool | None = None
    apc_amount: float | None = None
    notes: str | None = None


class JournalOut(BaseModel):
    """Représentation d'une revue dans les réponses de /api/journals.

    Source : SELECT dans list_journals (router journals). Les champs
    reflètent les colonnes retournées — pub_name (nom éditeur joint)
    et pub_count (agrégat) ne sont pas des colonnes de la table
    journals mais sont exposés aux clients.
    """

    id: int
    title: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    publisher_id: int | None
    pub_name: str | None
    openalex_id: str | None
    is_in_doaj: bool
    is_predatory: bool
    apc_amount: float | None
    apc_currency: str | None
    oa_model: str | None
    journal_type: str | None
    is_academic: bool | None
    doi_prefix: str | None
    notes: str | None
    pub_count: int


class JournalListResponse(BaseModel):
    total: int
    page: int
    pages: int
    journals: list[JournalOut]


class PublisherUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    doi_prefix: str | None = None
    is_predatory: bool | None = None
    notes: str | None = None


class MergeRequest(BaseModel):
    source_id: int


# ----- Publications -----


class MergePublications(BaseModel):
    target_id: int
    source_id: int


class MarkDistinctPublications(BaseModel):
    pub_id_a: int
    pub_id_b: int


class ExcludeSourceAuthorship(BaseModel):
    excluded: bool = True


# ----- Publications (output) -----


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


# --- Publications facets (génériques réutilisables) ---


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
    source_counts: dict[str, int]
    apc: list[TextStrFacet]
    countries: list[TextStrFacet]
    hal_status: list[TextStrFacet]
    in_perimeter: list[TextStrFacet]


# --- Publication detail ---


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

    author_position: int
    in_perimeter: bool
    is_corresponding: bool | None
    structure_ids: list[int] | None
    source_hal: bool
    source_openalex: bool
    source_wos: bool
    person_id: int
    last_name: str
    first_name: str


class SourceAuthorshipOut(BaseModel):
    """Authorship source (HAL / OpenAlex / WoS).

    `raw_affiliation` n'est calculé que pour OpenAlex et WoS ; absent
    côté HAL (défaut None).
    """

    id: int
    author_position: int | None
    full_name: str
    person_id: int | None
    in_perimeter: bool
    structure_ids: list[int] | None
    raw_affiliation: str | None = None
    excluded: bool
    countries: list[str] | None


class ThesesAuthorshipOut(BaseModel):
    id: int
    author_position: int | None
    full_name: str
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
    theses_authorships: list[ThesesAuthorshipOut]
    thesis_meta: ThesisMeta | None
    structures: dict[str, StructureInfo]


class ExcludeSourceAuthorshipResponse(BaseModel):
    ok: bool
    excluded: bool


# ----- Laboratories (output) -----


class LabTutelle(BaseModel):
    """Tutelle d'un labo (établissement, EPST, etc.) dans la liste."""

    id: int
    name: str
    acronym: str | None
    type: str


class LaboratoryListItem(BaseModel):
    """Ligne de `/api/laboratories` (liste du périmètre)."""

    id: int
    code: str
    name: str
    acronym: str | None
    ror_id: str | None
    hal_collection: str | None
    tutelles: list[LabTutelle] | None


class LabStructureCore(BaseModel):
    """Métadonnées du labo (bloc `structure` du détail)."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None


class LabRelatedStructure(BaseModel):
    """Structure voisine (tutelle, sous-labo) dans le détail d'un labo.

    Distinct de `RelatedStructureOut` (utilisé pour les structures
    génériques) — pas de `code` ni `relation_id` côté labo.
    """

    id: int
    name: str
    acronym: str | None
    type: str
    relation_type: str


class LaboratoryDetailResponse(BaseModel):
    structure: LabStructureCore
    parents: list[LabRelatedStructure]
    children: list[LabRelatedStructure]
    theses_count: int


class LabOrcidIdentifier(BaseModel):
    value: str
    confirmed: bool


class LabPersonOut(BaseModel):
    """Personne liée à un labo (onglet `persons`)."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    has_rh: bool
    pub_count: int
    orcids: list[LabOrcidIdentifier] | None


class LabBinaryFacet(BaseModel):
    """Facette binaire yes/no (compteur pour chaque option)."""

    yes: int
    no: int


class LabPersonsFacets(BaseModel):
    rh: LabBinaryFacet
    orcid: LabBinaryFacet
    idhal: LabBinaryFacet


class LabOrphanAuthorships(BaseModel):
    total: int


class LaboratoryPersonsResponse(BaseModel):
    total_persons: int
    page: int
    per_page: int
    pages: int
    persons: list[LabPersonOut]
    orphan_authorships: LabOrphanAuthorships
    facets: LabPersonsFacets


class LabAddressOut(BaseModel):
    id: int
    raw_text: str
    is_confirmed: bool | None


class LaboratoryAddressesResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    addresses: list[LabAddressOut]


class LabPubYearCount(BaseModel):
    year: int
    count: int


class LabDashboardOa(BaseModel):
    open_access: int
    closed: int
    unknown: int
    total: int


class LabDashboardCollab(BaseModel):
    total_articles: int
    international: int
    domestic: int


class LabTopCountry(BaseModel):
    code: str
    name: str
    count: int


class LaboratoryDashboardResponse(BaseModel):
    pubs_by_year: list[LabPubYearCount]
    oa: LabDashboardOa
    collab: LabDashboardCollab
    top_countries: list[LabTopCountry]


# ----- Addresses (output) -----


class AddressStructureSummary(BaseModel):
    """Lien adresse ↔ structure (élément de `structures` dans la liste/review)."""

    id: int
    name: str
    acronym: str | None
    is_confirmed: bool | None
    is_detected: bool


class AddressOut(BaseModel):
    """Ligne de `/api/addresses` (liste paginée pour validation)."""

    id: int
    raw_text: str
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]
    pub_count: int


class AddressListResponse(BaseModel):
    """Réponse paginée de `/api/addresses`.

    `requires_search=True` quand le caller utilise un filtre trop large
    (no/all + pas de search) et que le serveur a renvoyé une liste vide
    par garde-fou.
    """

    total: int
    page: int
    per_page: int
    pages: int
    addresses: list[AddressOut]
    requires_search: bool | None = None


class AddressPublicationItem(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    journal_title: str | None
    author_name: str | None
    source_id: str | None


class AddressPublicationsResponse(BaseModel):
    address_id: int
    raw_text: str
    publications: list[AddressPublicationItem]


class AddressReviewResponse(BaseModel):
    """Réponse de POST /api/addresses/{addr_id}/review."""

    id: int
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]


class BatchUpdatedResponse(BaseModel):
    updated: int


class BatchCountryResponse(BaseModel):
    """POST /api/addresses/batch-country : modifs directes + propagation."""

    updated: int
    propagated: int


class AddressOkResponse(BaseModel):
    ok: bool


class AssignStructureResponse(BaseModel):
    id: int
    structure_id: int
    status: str


class UnassignStructureResponse(BaseModel):
    deleted: bool


class CountryOut(BaseModel):
    code: str
    name: str


class CountrySuggestion(BaseModel):
    code: str
    count: int


class AddressForCountryAttribution(BaseModel):
    """Ligne de `/api/addresses/countries`."""

    id: int
    raw_text: str
    countries: list[str] | None
    suggested_countries: list[CountrySuggestion]
    pub_count: int


class AddressesCountriesResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    addresses: list[AddressForCountryAttribution]
    suggestion_facets: list[CountrySuggestion] | None = None
    country_facets: list[CountrySuggestion]


class CountrySuggestionsResponse(BaseModel):
    """GET /api/addresses/suggest-countries (admin)."""

    suggestions: list[CountrySuggestion]
    without_country: int


class AddressStatsResponse(BaseModel):
    """GET /api/admin/address-stats."""

    total: int
    detected: int
    pending: int
    rejected: int
    confirmed: int


# ----- Persons -----


class LinkPersonAuthor(BaseModel):
    author_id: int
    source: str  # 'hal' or 'openalex'


class AddIdentifier(BaseModel):
    id_type: str  # 'orcid' or 'idhal'
    id_value: str


class UpdateIdentifierStatus(BaseModel):
    status: Literal["pending", "confirmed", "rejected"]


class ReassignIdentifier(BaseModel):
    person_id: int


class RejectPerson(BaseModel):
    rejected: bool = True


class UpdatePersonName(BaseModel):
    last_name: str
    first_name: str = ""


class MergePersons(BaseModel):
    source_id: int


class MarkPersonsDistinct(BaseModel):
    person_id_a: int
    person_id_b: int


class CreatePersonName(BaseModel):
    last_name: str
    first_name: str = ""


class SourceAuthorshipRef(BaseModel):
    source: str
    authorship_id: int


class AssignOrphanAuthorship(BaseModel):
    source: str
    authorship_id: int
    person_id: int | None = None
    create_person: CreatePersonName | None = None


class BatchAssignOrphanAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    person_id: int


class DetachAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    name_form: str = ""


class DetachNameForm(BaseModel):
    name_form: str


# ----- Persons (output) -----


class PersonIdentifierOut(BaseModel):
    """Identifiant (ORCID, idHAL, idRef) attaché à une personne."""

    id: int
    id_type: str
    id_value: str
    source: str
    status: Literal["pending", "confirmed", "rejected"]


class LinkedAuthorOut(BaseModel):
    """Auteur source (HAL/OpenAlex/WoS) lié à une personne."""

    id: int
    source: str
    full_name: str


class NameFormSummaryOut(BaseModel):
    """Forme de nom observée pour une personne (liste admin)."""

    name_form: str
    sources: list[str]
    ambiguous: bool


class ValueConfirmedOut(BaseModel):
    """Identifiant sous forme condensée (annuaire public)."""

    value: str
    confirmed: bool


class PersonDirectoryEntry(BaseModel):
    """Ligne de l'annuaire public `/api/persons/directory`."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    has_rh: bool
    orcids: list[ValueConfirmedOut] | None
    idhals: list[ValueConfirmedOut] | None


class PersonDirectoryResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    persons: list[PersonDirectoryEntry]


class PersonSearchResult(BaseModel):
    """Résultat d'autocomplete `/api/persons/search`."""

    id: int
    last_name: str
    first_name: str
    department_name: str | None
    has_rh: bool


class PersonOut(BaseModel):
    """Ligne de `/api/persons` (liste admin)."""

    id: int
    last_name: str
    first_name: str
    last_name_normalized: str
    first_name_normalized: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None
    has_rh: bool
    rejected: bool
    pub_count: int
    uca_pub_count: int
    identifiers: list[PersonIdentifierOut] | None
    name_forms: list[NameFormSummaryOut] | None


class PersonListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    persons: list[PersonOut]


class FacetValueCount(BaseModel):
    value: str
    count: int


class YesNoCount(BaseModel):
    yes: int
    no: int


class PersonsFacetsResponse(BaseModel):
    """Réponse de `/api/persons/facets`."""

    departments: list[FacetValueCount]
    roles: list[FacetValueCount]
    orcid: YesNoCount
    idhal: YesNoCount
    rh: YesNoCount
    linked: YesNoCount


class DepartmentCount(BaseModel):
    department_name: str
    count: int


class RoleCount(BaseModel):
    role_title: str
    count: int


class PersonsStatsResponse(BaseModel):
    total_persons: int
    linked_persons: int
    linked_authors: int
    departments: int


class PersonDetail(BaseModel):
    """Réponse de `/api/persons/{id}` (détail + auteurs liés)."""

    id: int
    last_name: str
    first_name: str
    last_name_normalized: str
    first_name_normalized: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None
    has_rh: bool
    linked_authors: list[LinkedAuthorOut] | None
    identifiers: list[PersonIdentifierOut] | None


class PersonProfileCore(BaseModel):
    """Bloc `person` de `/api/persons/{id}/profile`."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None


class PersonProfileAuthor(BaseModel):
    """Auteur source dans `/api/persons/{id}/profile` (vue publique enrichie)."""

    id: int
    source: str
    full_name: str
    orcid: str | None
    idhal: str | None
    hal_person_id: int | None = None
    openalex_id: str | None
    uca_pub_count: int


class PersonProfileResponse(BaseModel):
    person: PersonProfileCore
    identifiers: list[PersonIdentifierOut]
    authors: list[PersonProfileAuthor]
    theses_count: int


class PersonThesis(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doi: str | None
    author_name: str | None
    author_person_id: int | None
    structure_ids: list[int]


class PersonThesesSection(BaseModel):
    role: str
    label: str
    theses: list[PersonThesis]


class StructureRef(BaseModel):
    """Référence courte à une structure (acronyme + nom)."""

    acronym: str | None
    name: str


class PersonThesesResponse(BaseModel):
    sections: list[PersonThesesSection]
    total: int
    structures: dict[int, StructureRef]


class PersonAddressStruct(BaseModel):
    id: int
    acronym: str | None
    name: str


class PersonAddressOut(BaseModel):
    id: int
    raw_text: str
    structures: list[PersonAddressStruct] | None


class PersonAddressesResponse(BaseModel):
    total: int
    page: int
    pages: int
    addresses: list[PersonAddressOut]


class NameFormAuthorshipRef(BaseModel):
    source: str
    authorship_id: int
    pub_id: int
    title: str
    pub_year: int | None
    doi: str | None


class OtherPersonOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    department_name: str | None
    has_rh: bool


class NameFormAuthorshipsResponse(BaseModel):
    authorships: list[NameFormAuthorshipRef]
    other_persons: list[OtherPersonOut]


class OrphanCountResponse(BaseModel):
    total: int


class OrphanAuthorshipOut(BaseModel):
    source: str
    authorship_id: int
    full_name: str
    publication_id: int
    pub_title: str
    pub_year: int | None


class OrphanAuthorshipsResponse(BaseModel):
    total: int
    page: int
    pages: int
    authorships: list[OrphanAuthorshipOut]


# ----- Persons (mutation responses) -----


class OkResponse(BaseModel):
    """Réponse minimale d'acquittement (pas de données)."""

    ok: bool = True


class RemovedResponse(BaseModel):
    removed: bool = True


class DetachedResponse(BaseModel):
    detached: bool = True


class AddIdentifierResponse(BaseModel):
    """Réponse de `POST /api/persons/{id}/identifiers`.

    Polymorphe selon le chemin :
    - doublon exact : `added=False` + `reason`
    - ajout normal  : `added=True` + `id_type` + `id_value`
    - réattribution : en plus, `reassigned=True`
    """

    added: bool
    reason: str | None = None
    id_type: str | None = None
    id_value: str | None = None
    reassigned: bool | None = None


class IdentifierStatusResponse(BaseModel):
    id: int
    status: str


class IdentifierReassignResponse(BaseModel):
    id: int
    person_id: int
    status: str


class AuthorshipExcludeResponse(BaseModel):
    id: int
    excluded: bool


class MergeResponse(BaseModel):
    merged: bool
    source_id: int
    target_id: int


class OrphanAssignResponse(BaseModel):
    ok: bool = True
    person_id: int


class OrphanBatchAssignResponse(BaseModel):
    ok: bool = True
    assigned: int


class DetachAuthorshipsResponse(BaseModel):
    detached: int
    deleted_authorships: int
    cleaned_form: bool


# ----- Config / Perimeters -----


class ConfigValueUpdate(BaseModel):
    """Corps de PUT /api/config/{key} : value JSON-sérialisable arbitraire."""

    value: Any


class AddPerimeterStructure(BaseModel):
    structure_id: int


class PerimeterCreate(BaseModel):
    code: str
    name: str
    description: str | None = None


class PerimeterUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    structure_ids: list[int] | None = None


# ----- Stats (output) -----


class OaCounts(BaseModel):
    """Agrégats communs aux lignes de stats (éditeurs, revues, labos).

    `apc_uca` est toujours numérique (coalescé à 0 côté SQL).
    """

    pub_count: int
    apc_uca: float
    gold: int
    diamond: int
    hybrid: int
    bronze: int
    green: int
    closed: int
    unknown: int


class PublisherStatsRow(OaCounts):
    publisher_id: int
    publisher_name: str
    journal_count: int


class JournalStatsRow(OaCounts):
    journal_id: int
    journal_title: str
    issn: str | None
    eissn: str | None
    publisher_name: str | None
    is_predatory: bool
    apc_amount: float | None


class LabStatsRow(OaCounts):
    lab_id: int
    lab_acronym: str | None
    lab_name: str


class PublisherStatsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    publishers: list[PublisherStatsRow]


class JournalStatsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    journals: list[JournalStatsRow]


class LabStatsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    labs: list[LabStatsRow]


class YearStatsRow(BaseModel):
    """Ventilation d'une année : pub_count + détail OA."""

    pub_year: int
    pub_count: int
    gold: int
    diamond: int
    hybrid: int
    bronze: int
    green: int
    closed: int
    unknown: int


class StatsSummary(BaseModel):
    """Totaux globaux pour la page stats.

    Pas de champ `diamond` — le résumé remonte gold/hybrid/green/bronze/
    closed/unknown uniquement (diamond non distingué côté summary SQL).
    """

    total_pubs: int
    gold: int
    hybrid: int
    green: int
    bronze: int
    closed: int
    unknown: int
    publisher_count: int
    journal_count: int


class YearFacet(BaseModel):
    value: int
    count: int


class LabFacet(BaseModel):
    value: int
    label: str
    count: int


class OaFacet(BaseModel):
    value: str
    count: int


class ApcFacet(BaseModel):
    value: Literal["uca", "non_uca", "none"]
    text: str
    count: int


class StatsFacetsResponse(BaseModel):
    years: list[YearFacet]
    labs: list[LabFacet]
    oa_statuses: list[OaFacet]
    apc: list[ApcFacet]
