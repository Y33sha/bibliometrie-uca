"""Port : lectures sur les publications (consommé par le router publications).

Les DTOs Pydantic sont co-localisés avec le `Protocol` (cf. décision 3
du chantier typage-projections-strict). Implémenté par
`infrastructure.queries.publications.PgPublicationsQueries`.

Les dataclasses `FacetFilters` et `ListFilters` vivent ici (source de
vérité) ; les fonctions infra les importent depuis ce module pour typer
leurs signatures (cf. règle 3 d'`architecture.md`).
"""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from application.ports.api._common import YesNoCount
from application.ports.api.subjects_queries import SubjectOut


@dataclass(frozen=True, slots=True)
class ListFilters:
    """Bundle des filtres pour list_publications / export_publications.
    Tous les champs ont un défaut — facilite les appels partiels."""

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    years: list[int] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    access: str = ""
    oa_status: str = ""
    source_values: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    person_id: int | None = None
    is_corresponding: str = ""
    has_apc: str = ""
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: str = ""
    subject_id: int | None = None


@dataclass(frozen=True, slots=True)
class FacetFilters:
    """Bundle spécifique aux facettes (similaire à ListFilters mais sans
    pagination/sort)."""

    years: list[int] = field(default_factory=list)
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    access: str = ""
    oa_status: str = ""
    source_values: list[str] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    person_id: int | None = None
    is_corresponding: str = ""
    has_apc: str = ""
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: str = ""
    subject_id: int | None = None


# ---------------------------------------------------------------------------
# DTOs Listing
# ---------------------------------------------------------------------------


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
    journal_id: int | None
    publisher: str | None
    hal_id: str | None
    openalex_id: str | None
    scanr_id: str | None
    wos_id: str | None
    theses_id: str | None
    date_soutenance: str | None
    date_inscription: str | None
    thesis_author_name: str | None
    thesis_author_person_id: int | None
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


# ---------------------------------------------------------------------------
# DTOs Facettes
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DTOs Détail publication
# ---------------------------------------------------------------------------


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
    """École doctorale d'une thèse (metadata theses.fr).

    Sert à la fois de DTO API (champ de `ThesisMeta` dans la réponse
    détail publication) et de modèle de la colonne JSONB `meta.ecoles_doctorales`
    (importé par `infrastructure/jsonb_models/publication.py`).
    `extra="allow"` pour tolérer des clés inconnues côté JSONB sans casser.
    """

    model_config = ConfigDict(extra="allow")
    nom: str
    ppn: str | None = None  # IdRef de l'ED quand disponible


class PartenaireThese(BaseModel):
    """Partenaire de recherche d'une thèse (metadata theses.fr).

    Sert à la fois de DTO API et de modèle de la colonne JSONB
    `meta.partenaires`. `extra="allow"` pour tolérer des clés inconnues
    côté JSONB sans casser.
    """

    model_config = ConfigDict(extra="allow")
    nom: str
    type: str | None = None  # ex: "etablissement", "laboratoire", …


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


class PublicationsQueries(Protocol):
    """Lectures sync pour /api/publications/*."""

    def list_publications(
        self,
        *,
        filters: ListFilters,
        apc_structure_ids: list[int],
        page: int,
        per_page: int,
        sort: str,
    ) -> PublicationListResponse: ...

    def publications_facets(
        self, *, filters: FacetFilters, apc_structure_ids: list[int]
    ) -> PublicationsFacetsResponse: ...

    def export_publications_csv(
        self, *, filters: ListFilters, apc_structure_ids: list[int], sort: str
    ) -> str: ...

    def export_theses_csv(
        self, *, filters: ListFilters, apc_structure_ids: list[int], sort: str
    ) -> str: ...

    def get_publication_detail(self, pub_id: int) -> PublicationDetailResponse | None: ...
