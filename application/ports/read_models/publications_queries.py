"""Port : lectures sur les publications (consommé par le router publications).

Implémenté par `infrastructure.read_models.publications.PgPublicationsQueries`. Les modèles Pydantic que ces lectures rendent sont co-localisés avec le `Protocol` : leur contrat appartient au port.

La dataclass `PublicationFilters` fait ici référence ; l'infrastructure l'importe pour typer ses signatures.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from application.ports.read_models._common import (
    EntityFacetResponse,
    EntityKind,
    FacetOption,
    PaginatedResponse,
    YesNoCount,
)
from application.ports.read_models.subjects_queries import SubjectOut
from domain.publications.licenses import License

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
]


# Vocabulaire des colonnes que l'export des publications sait émettre, dans l'ordre où elles
# paraissent. L'appelant nomme celles qu'il veut voir ; une liste vide les demande toutes. Le
# titre et les liens paraissent quoi qu'il arrive.
EXPORT_COLUMNS: frozenset[str] = frozenset(
    {
        "type",
        "year",
        "title",
        "journal",
        "publisher",
        "labs",
        "corr",
        "apc",
        "oa",
        "oa_status",
        "license",
        "hal_status",
        "links",
    }
)


# Vocabulaire du filtre par licence de la version éditeur : les licences du domaine, et `none` pour une publication sans licence connue.
NO_LICENSE = "none"
LICENSE_FILTER_VALUES: frozenset[str] = frozenset({*License, NO_LICENSE})


@dataclass(frozen=True, slots=True)
class PublicationFilters:
    """Filtres de la page publications, partagés par la liste, les facettes et l'export.

    Les trois lectures répondent aux mêmes questions sur le même ensemble : leurs décomptes, leurs lignes et leur export ne se recouperaient pas si elles n'écoutaient pas les mêmes filtres. Tous les champs ont un défaut, ce qui autorise les constructions partielles.

    Les listes valent absence de filtre quand elles sont vides. `lab_none` retient les publications qu'aucun laboratoire ne signe ; `is_corresponding`, `in_perimeter` et `has_apc` prennent des valeurs de `yes` / `no` combinées en OR, où cocher les deux ne contraint rien. `has_apc` retient les publications dont un paiement d'APC est imputé au budget d'une structure du périmètre.

    `person_id` définit l'ensemble d'une page personne : toutes les publications de la personne, dans le périmètre ou hors de lui. `author_id` restreint l'ensemble courant aux publications d'un auteur ; les deux se combinent.
    """

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    years: list[int] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    monograph_id: int | None = None
    access: list[str] = field(default_factory=list)
    oa_status: list[str] = field(default_factory=list)
    license: list[str] = field(default_factory=list)
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
    # Paiement sur le budget d'une structure du périmètre des personnes, même règle que le filtre `has_apc`.
    in_perimeter: bool


class PublicationListItem(BaseModel):
    """Ligne de `/api/publications` (liste + recherche)."""

    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    oa_status: str
    license: str | None  # licence de la version éditeur
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
    licenses: list[FacetOption]
    corresponding: list[FacetOption]
    source_counts: dict[str, YesNoCount]
    apc: list[FacetOption]
    countries: list[FacetOption]
    languages: list[FacetOption]
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
    license: str | None  # licence de la version éditeur
    deposit_license: str | None  # licence du fichier déposé dans HAL
    language: str | None
    container_title: str | None
    abstract: str | None
    journal_id: int | None
    journal_title: str | None
    journal_issns: list[str]
    """ISSN actifs de la revue."""
    apc_amount: float | None
    apc_currency: str | None
    oa_model: str | None
    monograph_id: int | None
    """Livre ou volume d'actes qui contient la publication."""
    monograph_title: str | None
    publisher_id: int | None
    """Éditeur de la revue, à défaut celui de la monographie."""
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


class ThesesAuthorshipOut(BaseModel):
    id: int
    author_position: int | None
    full_name: str | None
    person_id: int | None
    roles: list[str]
    in_perimeter: bool


class EcoleDoctorale(BaseModel):
    """École doctorale d'une thèse (metadata theses.fr), champ de `ThesisMeta` dans la réponse détail publication.

    Lu depuis la colonne JSONB `meta.ecoles_doctorales`. `extra="allow"` tolère les clés inconnues du JSONB.
    """

    model_config = ConfigDict(extra="allow")
    nom: str
    ppn: str | None = None  # IdRef de l'ED quand disponible


class PartenaireThese(BaseModel):
    """Partenaire de recherche d'une thèse (metadata theses.fr), champ de `ThesisMeta` dans la réponse détail publication.

    Lu depuis la colonne JSONB `meta.partenaires`. `extra="allow"` tolère les clés inconnues du JSONB.
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
    theses_authorships: list[ThesesAuthorshipOut]
    thesis_meta: ThesisMeta | None
    structures: dict[str, StructureInfo]
    subjects: list[SubjectOut]
    keywords: list[str]  # mots-clés libres agrégés des sources (hors référentiel `subjects`)
    relations: list[RelatedPublicationOut]
    external_identifiers: list[ExternalIdentifierOut]


class SourcePublicationMetadataOut(BaseModel):
    """Métadonnées d'un enregistrement source, après normalisation.

    `journal_id` et `journal_title` désignent la revue du référentiel où l'enregistrement est rattaché, `publisher_id` et `publisher_name` l'éditeur de cette revue. Les champs `journal_raw_*` et `publisher_raw_name` portent la revue et l'éditeur tels que la source les donne. `pages` reprend la plage de pages de la source, ou la compose de la première et de la dernière page. `language_name` est le nom de la langue dans le référentiel ; `language_raw`, la valeur que donnait la source quand la normalisation l'a changée.
    """

    id: int
    source: str
    source_id: str
    doi: str | None
    identifiers: dict[str, list[str]]  # `external_ids` hors ISSN, chaque valeur en liste
    title: str
    title_normalized: str | None  # forme de comparaison du titre
    doc_type: str | None
    pub_year: int | None
    language: str | None
    language_name: str | None
    language_raw: str | None
    oa_status: str | None
    journal_id: int | None
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


class SourceSignatureOut(BaseModel):
    """Signature d'un enregistrement source, avec son groupe : les signatures d'un même auteur dans la publication.

    `position` : rang d'auteur dans l'enregistrement, à partir de 0 ; absent pour un rôle hors de la liste d'auteurs. `raw_affiliation` réunit les adresses brutes de la signature. `group_id` et `group_position`, position de la signature de référence du groupe : absents pour une signature hors des groupes (collective, ou enregistrement écarté de l'alignement). `method`, `score`, `margin` : entrée de la signature dans son groupe ; score et marge en bits, pour le modèle.
    """

    id: int
    source_publication_id: int
    position: int | None
    full_name: str | None
    roles: list[str] | None
    person_id: int | None
    in_perimeter: bool
    collective: bool
    structure_ids: list[int] | None
    raw_affiliation: str | None
    countries: list[str] | None
    group_id: int | None
    group_position: int | None
    method: str | None
    score: float | None
    margin: float | None


class PublicationSourcesResponse(BaseModel):
    """Enregistrements sources d'une publication, toutes sources confondues, leurs signatures, et les structures que ces signatures citent."""

    title: str
    source_publications: list[SourcePublicationMetadataOut]
    signatures: list[SourceSignatureOut]
    structures: dict[str, StructureInfo]


class SuspectMergeNoticeOut(BaseModel):
    """Notice d'une publication de la file des fusions suspectes, et ses signatures d'auteur."""

    source: str
    source_id: str
    signatures: int
    rule_aligned_signatures: int
    lone_signatures: int


class SuspectMergeOut(BaseModel):
    """Publication dont moins de la moitié des signatures d'auteur sont alignées par la règle : ses notices ont des listes d'auteurs qui ne se recouvrent pas.

    `rule_aligned_signatures` : signatures d'auteur d'un groupe dont un membre est lié par la règle (nom, identifiant, ordre). `lone_signatures` : signatures d'auteur seules dans leur groupe. `model_signatures` : signatures d'auteur liées à leur groupe par le modèle ; `min_margin` : plus petite marge de ces liens, en bits.
    """

    publication_id: int
    title: str
    pub_year: int | None
    doc_type: str
    signatures: int
    rule_aligned_signatures: int
    lone_signatures: int
    model_signatures: int
    min_margin: float | None
    notices: list[SuspectMergeNoticeOut]


class SuspectMergesResponse(PaginatedResponse):
    publications: list[SuspectMergeOut]


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
    ) -> Iterator[str]: ...

    def export_theses_csv(
        self, *, filters: PublicationFilters, sort: PublicationSort
    ) -> Iterator[str]: ...

    def get_publication_detail(self, pub_id: int) -> PublicationDetailResponse | None: ...

    def get_publication_sources(self, pub_id: int) -> PublicationSourcesResponse | None:
        """Métadonnées de chaque enregistrement source de la publication ; `None` si la publication n'existe pas."""
        ...

    def suspect_merges_count(self) -> int: ...

    def suspect_merges(self, *, page: int, per_page: int) -> SuspectMergesResponse:
        """Fusions suspectes, la plus faible part de signatures d'auteur alignées par la règle d'abord."""
        ...
