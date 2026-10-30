"""Modèles de réponse : lectures sur les publications."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from domain.publications.licenses import License
from domain.sources.registry import PROFILES, Source, source_record_url
from infrastructure.read_models._common import (
    FacetOption,
    PaginatedResponse,
    YesNoCount,
)
from infrastructure.read_models.subjects.models import SubjectOut

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
    "inscription_asc",
    "inscription_desc",
    "author_asc",
    "author_desc",
    "labs_asc",
    "labs_desc",
    "serial_asc",
    "serial_desc",
    "publisher_asc",
    "publisher_desc",
]


# Vocabulaire des colonnes que l'export des publications sait émettre, dans l'ordre où elles paraissent. L'appelant nomme celles qu'il veut voir ; une liste vide les demande toutes. Le titre et les liens paraissent quoi qu'il arrive.
EXPORT_COLUMNS: frozenset[str] = frozenset(
    {
        "type",
        "year",
        "title",
        "serial",
        "publisher",
        "labs",
        "corr",
        "apc",
        "doi",
        "oa_status",
        "license",
        "hal_status",
        "sources",
        "access",
    }
)


# Vocabulaire des colonnes que l'export des thèses sait émettre, aux règles de `EXPORT_COLUMNS`.
THESIS_EXPORT_COLUMNS: frozenset[str] = frozenset(
    {
        "inscription",
        "soutenance",
        "author",
        "doi",
        "title",
        "status",
        "labs",
        "sources",
        "access",
    }
)


# Vocabulaire du filtre par licence de la version éditeur : les licences du domaine, et `none` pour une publication sans licence connue.
NO_LICENSE = "none"
LICENSE_FILTER_VALUES: frozenset[str] = frozenset({*License, NO_LICENSE})

# Vocabulaire du filtre par agence d'enregistrement du DOI, dans l'ordre de la facette : les sources qui représentent une agence (`registration_agency`), `other` pour les autres agences, `none` pour une publication sans DOI.
DOI_AGENCY_SOURCES: tuple[Source, ...] = tuple(
    source for source, profile in PROFILES.items() if profile.registration_agency
)
OTHER_DOI_AGENCY = "other"
NO_DOI = "none"
DOI_AGENCY_FILTER_VALUES: tuple[str, ...] = (*DOI_AGENCY_SOURCES, OTHER_DOI_AGENCY, NO_DOI)


@dataclass(frozen=True, slots=True)
class PublicationFilters:
    """Filtres de la page publications, partagés par la liste, les facettes et l'export.

    Les trois lectures comptent le même ensemble sous les mêmes filtres. Tous les champs ont un défaut : une construction partielle est possible.

    Une liste vide laisse tout passer. `lab_none` retient les publications sans laboratoire ; `is_corresponding`, `in_perimeter` et `has_apc` prennent des valeurs `yes` et `no` combinées en OR : cocher les deux laisse tout passer. `has_apc` retient les publications dont un paiement d'APC est imputé au budget d'une structure du périmètre.

    `person_id` définit l'ensemble d'une page personne : toutes les publications de la personne, dans le périmètre ou hors de lui. `author_id` restreint l'ensemble courant aux publications d'un auteur ; les deux se combinent.
    """

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    years: list[int] = field(default_factory=list)
    publisher_id: int | None = None
    serial_id: int | None = None
    monograph_id: int | None = None
    access: list[str] = field(default_factory=list)
    oa_status: list[str] = field(default_factory=list)
    license: list[str] = field(default_factory=list)
    doi_agency: list[str] = field(default_factory=list)
    source_values: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    person_id: int | None = None
    author_id: int | None = None
    is_corresponding: list[str] = field(default_factory=list)
    has_apc: list[str] = field(default_factory=list)
    country_values: list[str] = field(default_factory=list)
    language_codes: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: list[str] = field(default_factory=list)
    subject_ids: list[int] = field(default_factory=list)
    partner_rors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------


class PublicationLabItem(BaseModel):
    id: int
    label: str


class PublicationApcPayment(BaseModel):
    """Détail d'un paiement APC (une ligne d'`apc` dans la liste)."""

    amount: float
    institution: str | None
    lab_id: int | None
    lab_acronym: str | None
    budget_structure_id: int | None
    # Paiement sur le budget d'une structure du périmètre des personnes, même règle que le filtre `has_apc`.
    in_perimeter: bool


class PublicationListItem(BaseModel):
    """Ligne de `/api/publications` (liste et recherche)."""

    id: int
    title: str
    publication_year: int | None
    doi: str | None
    doc_type: str
    oa_status: str
    access_url: str | None
    """Lien d'accès (`domain.publications.access.access_url`)."""
    license: str | None  # licence de la version éditeur
    serial: str | None
    serial_id: int | None
    publisher: str | None
    publisher_id: int | None
    hal_id: str | None
    openalex_id: str | None
    scanr_id: str | None
    wos_id: str | None
    theses_id: str | None

    @computed_field
    @property
    def record_urls(self) -> dict[str, str]:
        """Lien vers le portail de chaque source où la publication est présente."""
        ids = {
            Source.HAL: self.hal_id,
            Source.OPENALEX: self.openalex_id,
            Source.SCANR: self.scanr_id,
            Source.WOS: self.wos_id,
            Source.THESES: self.theses_id,
        }
        return {
            source: source_record_url(source, source_id, self.oa_status)
            for source, source_id in ids.items()
            if source_id
        }

    date_soutenance: str | None
    date_inscription: str | None
    thesis_author_name: str | None
    thesis_author_person_id: int | None
    lab_items: list[PublicationLabItem] | None
    apc: list[PublicationApcPayment] | None
    is_corresponding: bool | None
    contribution_id: int | None
    hal_status: str | None
    """Statut de dépôt HAL (`HAL_DEPOSIT_STATUSES`) au regard de la collection du laboratoire, quand la liste porte sur un seul laboratoire ; `None` sinon."""


class PublicationListResponse(PaginatedResponse):
    publications: list[PublicationListItem]


# ---------------------------------------------------------------------------
# Facettes
# ---------------------------------------------------------------------------


class PublicationsFacetsResponse(BaseModel):
    """Facettes dynamiques pour la page publications.

    Chaque facette exclut son propre filtre mais applique tous les autres. `hal_status` est rempli seulement quand un seul laboratoire est sélectionné, `corresponding` et `in_perimeter` seulement avec `person_id`.
    """

    years: list[FacetOption]
    labs: list[FacetOption]
    no_lab_count: int
    doc_types: list[FacetOption]
    access: list[FacetOption]
    oa_statuses: list[FacetOption]
    licenses: list[FacetOption]
    doi_agencies: list[FacetOption]
    corresponding: list[FacetOption]
    source_counts: dict[str, YesNoCount]
    apc: list[FacetOption]
    countries: list[FacetOption]
    languages: list[FacetOption]
    hal_status: list[FacetOption]
    in_perimeter: list[FacetOption]


# ---------------------------------------------------------------------------
# Détail d'une publication
# ---------------------------------------------------------------------------


class PublicationDetailCore(BaseModel):
    """Métadonnées de la publication (bloc `publication` du détail)."""

    id: int
    title: str
    publication_year: int | None
    doi: str | None
    doi_ra: (
        str | None
    )  # Agence d'enregistrement du préfixe DOI (Crossref, DataCite), d'après `doi_prefixes`.
    doc_type: str
    oa_status: str
    license: str | None  # licence de la version éditeur
    deposit_license: str | None  # licence du fichier déposé dans HAL
    language: str | None
    container_title: str | None
    abstract: str | None
    serial_id: int | None
    journal_title: str | None
    serial_issns: list[str]
    """ISSN actifs de la revue."""
    oa_model: str | None
    monograph_id: int | None
    """Livre ou volume d'actes qui contient la publication."""
    monograph_title: str | None
    publisher_id: int | None
    """Éditeur de la revue, à défaut celui de la monographie."""
    publisher_name: str | None


class SourceRecordOut(BaseModel):
    source: str
    source_id: str
    oa_status: str | None
    doi: str | None
    hal_collections: list[str] | None
    countries: list[str] | None

    @computed_field
    @property
    def record_url(self) -> str:
        """Lien vers l'enregistrement sur le portail de sa source."""
        return source_record_url(self.source, self.source_id, self.oa_status)


class ExternalIdentifierOut(BaseModel):
    """Identifiant d'une publication ou d'un enregistrement source : type de `source_record_identifiers` et valeur."""

    type: str
    value: str


class AccessLinkOut(BaseModel):
    """Copie ouverte d'une publication, nommée par sa plateforme (`domain.publications.access`)."""

    label: str
    url: str
    known: bool
    """La copie est hébergée par une plateforme du registre."""


class ConsolidatedContributionOut(BaseModel):
    """Contribution d'une personne à la publication."""

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
    has_rh: bool  # la personne est rattachée au référentiel RH (hr_records)


class ThesesContributionOut(BaseModel):
    id: int
    author_position: int | None
    full_name: str | None
    person_id: int | None
    roles: list[str]
    in_perimeter: bool


class EcoleDoctorale(BaseModel):
    """École doctorale d'une thèse, d'après theses.fr (`source_extras.ecoles_doctorales`). `extra="allow"` accepte les clés inconnues."""

    model_config = ConfigDict(extra="allow")
    nom: str
    ppn: str | None = None  # PPN IdRef de l'école doctorale, s'il est connu.


class PartenaireThese(BaseModel):
    """Partenaire de recherche d'une thèse, d'après theses.fr (`source_extras.partenaires`). `extra="allow"` accepte les clés inconnues."""

    model_config = ConfigDict(extra="allow")
    nom: str
    type: str | None = None  # `etablissement`, `laboratoire`…


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
    is_laboratory: bool


class RelatedPublicationOut(BaseModel):
    """Une publication apparentée, vue depuis la publication courante.

    `relation_type` se lit depuis la publication courante : les relations entrantes sont inversées. Une cible du corpus a son identifiant, son titre, son année et son type, et son DOI s'il existe ; elle se lie par son identifiant. Une cible hors corpus a son seul DOI.
    """

    relation_type: str
    doi: str | None = None
    publication_id: int | None = None
    title: str | None = None
    publication_year: int | None = None
    doc_type: str | None = None
    source: str


class PublicationDetailResponse(BaseModel):
    """Détail complet d'une publication : métadonnées, sources et contributions."""

    publication: PublicationDetailCore
    sources: list[SourceRecordOut]
    contributions: list[ConsolidatedContributionOut]
    theses_contributions: list[ThesesContributionOut]
    thesis_meta: ThesisMeta | None
    structures: dict[str, StructureInfo]
    subjects: list[SubjectOut]
    keywords: list[str]  # mots-clés libres agrégés des sources (hors référentiel `subjects`)
    relations: list[RelatedPublicationOut]
    access_url: str | None
    """Lien d'accès (`domain.publications.access.access_url`)."""
    access: list[AccessLinkOut]
    """Meilleure copie ouverte de chaque plateforme, la meilleure en tête, hors copies désignées par le DOI."""
    referenced_by: list[SourceRecordOut]
    """Sources qui référencent la publication sans en donner de copie : toutes, sauf Crossref et DataCite, que couvre le DOI, et HAL quand HAL figure parmi les liens d'accès."""
    external_identifiers: list[ExternalIdentifierOut]


class SourceRecordMetadataOut(BaseModel):
    """Métadonnées d'un enregistrement source, après normalisation.

    `serial_id` et `journal_title` désignent la revue du référentiel où l'enregistrement est rattaché, `publisher_id` et `publisher_name` l'éditeur que nomme la source, rattaché au référentiel. Les champs `journal_raw_*` et `publisher_raw_name` contiennent la revue et l'éditeur tels que la source les donne. `pages` reprend la plage de pages de la source, ou la compose de la première et de la dernière page. `language_name` est le nom de la langue dans le référentiel ; `language_raw`, la valeur que donnait la source quand la normalisation l'a changée. `raw_doc_type` est le type dans le vocabulaire de la source. Pour un type corrigé, `doc_type_uncorrected` est le type d'avant correction et `doc_type_corrected_by` la règle de correction.
    """

    id: int
    source: str
    source_id: str
    doi: str | None
    identifiers: list[ExternalIdentifierOut]  # identifiants actifs, hors DOI du champ `doi`
    title: str
    title_normalized: str | None  # forme de comparaison du titre
    doc_type: str | None
    raw_doc_type: str | None
    doc_type_uncorrected: str | None
    doc_type_corrected_by: str | None
    publication_year: int | None
    language: str | None
    language_name: str | None
    language_raw: str | None
    oa_status: str | None
    serial_id: int | None
    journal_title: str | None
    journal_raw_title: str | None
    journal_raw_issn: str | None
    journal_raw_eissn: str | None
    publisher_id: int | None
    publisher_name: str | None
    publisher_raw_name: str | None
    container_title: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    article_number: str | None

    @computed_field
    @property
    def record_url(self) -> str:
        """Lien vers l'enregistrement sur le portail de sa source."""
        return source_record_url(self.source, self.source_id, self.oa_status)


class SourceContributionOut(BaseModel):
    """Contribution source d'un enregistrement source, avec sa contribution : les contributions sources d'un même auteur dans la publication.

    `position` est le rang d'auteur dans l'enregistrement source, à partir de 0 ; il manque pour un rôle hors de la liste d'auteurs. `raw_affiliation` réunit les adresses brutes. `contribution_id` et `reference_position` (position de la contribution source de référence de la contribution) manquent pour une contribution source en attente d'alignement. `person_id` est la personne de la contribution. `method`, `score` et `margin` décrivent l'entrée de la contribution source dans sa contribution ; score et marge sont en bits.
    """

    id: int
    source_record_id: int
    position: int | None
    full_name: str | None
    roles: list[str] | None
    person_id: int | None
    in_perimeter: bool
    structure_ids: list[int] | None
    raw_affiliation: str | None
    countries: list[str] | None
    contribution_id: int | None
    reference_position: int | None
    method: str | None
    score: float | None
    margin: float | None


class PublicationSourcesResponse(BaseModel):
    """Enregistrements sources d'une publication, toutes sources confondues, leurs contributions sources, et les structures que ces contributions sources citent."""

    title: str
    source_records: list[SourceRecordMetadataOut]
    source_contributions: list[SourceContributionOut]
    structures: dict[str, StructureInfo]


class SuspectMergeSourceRecordOut(BaseModel):
    """Enregistrement source d'une publication de la file des fusions suspectes, et ses contributions sources d'auteur."""

    source: str
    source_id: str
    source_contributions: int
    matched_source_contributions: int

    @computed_field
    @property
    def record_url(self) -> str:
        """Lien vers l'enregistrement sur le portail de sa source."""
        return source_record_url(self.source, self.source_id)


class SuspectMergeOut(BaseModel):
    """Publication dont moins de la moitié des contributions sources d'auteur ont un correspondant dans un autre enregistrement source : ses enregistrements sources ont des listes d'auteurs qui ne se recouvrent pas."""

    publication_id: int
    title: str
    publication_year: int | None
    doc_type: str
    source_contributions: int
    matched_source_contributions: int
    source_records: list[SuspectMergeSourceRecordOut]


class SuspectMergesResponse(PaginatedResponse):
    publications: list[SuspectMergeOut]


class MergeCandidateOut(BaseModel):
    """Publication fusionnable avec une autre. `similarity` : similarité trigramme de son titre normalisé avec le titre de référence. `sources` : sources de ses enregistrements sources."""

    publication_id: int
    title: str
    publication_year: int | None
    doc_type: str
    doi: str | None
    similarity: float
    sources: list[str]
