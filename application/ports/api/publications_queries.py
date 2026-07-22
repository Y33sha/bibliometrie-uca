"""Port : lectures sur les publications (consommé par le router publications).

Implémenté par `infrastructure.queries.api.publications.PgPublicationsQueries`. Les modèles Pydantic que ces lectures rendent sont co-localisés avec le `Protocol` : leur contrat appartient au port.

La dataclass `PublicationFilters` fait ici référence ; l'infrastructure l'importe pour typer ses signatures (règle 3 de `docs/architecture/01-vue-d-ensemble.md`).
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from application.ports.api._common import FacetOption, PaginatedResponse, YesNoCount
from application.ports.api.entity_facet import EntityFacetResponse, EntityKind
from application.ports.api.subjects_queries import SubjectOut

# Vocabulaire de tri des listes de publications, thèses comprises : le champ, puis le sens.
PublicationSort = Literal[
    "year_asc",
    "year_desc",
    "title_asc",
    "title_desc",
    "apc_asc",
    "apc_desc",
    "soutenance_asc",
    "soutenance_desc",
]


@dataclass(frozen=True, slots=True)
class PublicationFilters:
    """Filtres de la page publications, partagés par la liste, les facettes et l'export.

    Les trois lectures répondent aux mêmes questions sur le même ensemble : leurs décomptes, leurs lignes et leur export ne se recouperaient pas si elles n'écoutaient pas les mêmes filtres. Tous les champs ont un défaut, ce qui autorise les constructions partielles.

    Les listes valent absence de filtre quand elles sont vides. `lab_none` retient les publications qu'aucun laboratoire ne signe ; `is_corresponding`, `has_apc` et `in_perimeter` portent une sélection de `yes` / `no` combinée en OR, où cocher les deux ne contraint rien.
    """

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    years: list[int] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    access: list[str] = field(default_factory=list)
    oa_status: list[str] = field(default_factory=list)
    source_values: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    person_id: int | None = None
    is_corresponding: list[str] = field(default_factory=list)
    has_apc: list[str] = field(default_factory=list)
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: list[str] = field(default_factory=list)
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
    publisher_id: int | None
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


class PublicationListResponse(PaginatedResponse):
    publications: list[PublicationListItem]


# ---------------------------------------------------------------------------
# DTOs Facettes
# ---------------------------------------------------------------------------


class PublicationsFacetsResponse(BaseModel):
    """Facettes dynamiques pour la page publications.

    Chaque facette exclut son propre filtre mais applique tous les autres. `hal_status` est vide tant qu'un labo unique n'est pas sélectionné. `corresponding`, `in_perimeter` sont vides sans `person_id`.
    """

    years: list[FacetOption]
    labs: list[FacetOption]
    no_lab_count: int
    doc_types: list[FacetOption]
    access: list[FacetOption]
    oa_statuses: list[FacetOption]
    corresponding: list[FacetOption]
    source_counts: dict[str, YesNoCount]
    apc: list[FacetOption]
    countries: list[FacetOption]
    hal_status: list[FacetOption]
    in_perimeter: list[FacetOption]


# ---------------------------------------------------------------------------
# DTOs Détail publication
# ---------------------------------------------------------------------------


class PublicationDetailCore(BaseModel):
    """Métadonnées de la publication (bloc `publication` du détail)."""

    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doi_ra: str | None  # registration agency du préfixe DOI (Crossref / DataCite), via doi_prefixes
    doc_type: str
    oa_status: str
    language: str | None
    container_title: str | None
    abstract: str | None
    journal_id: int | None
    journal_title: str | None
    issn: str | None
    eissn: str | None
    apc_amount: float | None
    apc_currency: str | None
    oa_model: str | None
    publisher_id: int | None
    publisher_name: str | None


class SourcePublicationOut(BaseModel):
    source: str
    source_id: str
    doi: str | None
    hal_collections: list[str] | None
    countries: list[str] | None
    # Forme secondaire convergée (pièce, version ou variante dont le DOI a été substitué par
    # celui de l'œuvre canonique). La fiche replie ces sources sous un groupe dépliable.
    is_secondary: bool


class ExternalIdentifierOut(BaseModel):
    """Identifiant externe agrégé d'une publication (arXiv, PMID, PMCID, NNT), pour la sidebar."""

    type: str  # "arxiv" | "pmid" | "pmcid" | "nnt"
    value: str


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
    has_rh: bool  # la personne est rattachée au référentiel RH (persons_rh)


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


class RelatedPublicationOut(BaseModel):
    """Une publication apparentée, vue depuis la publication courante.

    `relation_type` est exprimé du point de vue de la publication courante (les relations entrantes sont inversées). `publication_id`/`title`/`pub_year`/`doc_type` sont renseignés quand la cible est au corpus ; le `doi` peut être absent (cible au corpus sans DOI), auquel cas la cible se lie par son `publication_id` ; une cible hors corpus n'a, elle, que son `doi`."""

    relation_type: str
    doi: str | None = None
    publication_id: int | None = None
    title: str | None = None
    pub_year: int | None = None
    doc_type: str | None = None
    source: str


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
    keywords: list[str]  # mots-clés libres agrégés des sources (hors référentiel `subjects`)
    relations: list[RelatedPublicationOut]
    external_identifiers: list[ExternalIdentifierOut]


class PublicationsQueries(Protocol):
    """Lectures sync pour /api/publications/*.

    Le filtre `has_apc` de `PublicationFilters` s'appuie sur le périmètre des structures internes, que l'implémentation résout elle-même.
    """

    def list_publications(
        self,
        *,
        filters: PublicationFilters,
        page: int,
        per_page: int,
        sort: PublicationSort,
    ) -> PublicationListResponse: ...

    def publications_facets(self, *, filters: PublicationFilters) -> PublicationsFacetsResponse: ...

    def publications_entity_facet(
        self, *, kind: EntityKind, search: str, filters: PublicationFilters
    ) -> EntityFacetResponse: ...

    def export_publications_csv(
        self,
        *,
        filters: PublicationFilters,
        sort: PublicationSort,
        columns: list[str],
    ) -> str: ...

    def export_theses_csv(self, *, filters: PublicationFilters, sort: PublicationSort) -> str: ...

    def get_publication_detail(self, pub_id: int) -> PublicationDetailResponse | None: ...


# ── Doublons (page admin de déduplication) ──────────────────────────
# Contrat distinct de `PublicationsQueries` (ségrégation d'interface) : la page de
# dédoublonnage est un usage admin à part, servi par le même routeur publications.


class DuplicateJournal(BaseModel):
    id: int
    title: str | None
    issn: str | None
    eissn: str | None


class DuplicateSource(BaseModel):
    source: str
    source_id: str


class DuplicateAuthor(BaseModel):
    author_position: int | None
    in_perimeter: bool
    person_id: int | None
    last_name: str | None
    first_name: str | None
    full_name: str | None


class DuplicatePublicationDetail(BaseModel):
    """Détail d'une publication pour la page de déduplication."""

    id: int
    title: str
    title_normalized: str
    doi: str | None
    pub_year: int | None
    doc_type: str
    container_title: str | None
    oa_status: str
    language: str | None
    journal: DuplicateJournal | None
    sources: list[DuplicateSource]
    authors: list[DuplicateAuthor]


class DuplicatePair(BaseModel):
    pub_a: DuplicatePublicationDetail
    pub_b: DuplicatePublicationDetail


class DuplicatePairResponse(BaseModel):
    total: int
    offset: int
    pair: DuplicatePair | None


class PublicationDuplicatesQueries(Protocol):
    """Lectures pour le dédoublonnage des publications (page admin `/api/publications/duplicates/*`)."""

    def next_pub_duplicate(self, *, min_title_len: int, offset: int) -> DuplicatePairResponse: ...
