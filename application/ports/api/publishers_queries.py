"""Port : lectures sur les éditeurs (consommé par le router publishers).

Implémenté par `infrastructure.queries.api.publishers.PgPublisherQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4 — les DTOs vivent dans le port qui les définit (zone neutre, à côté des Protocols).
"""

from typing import Protocol

from pydantic import BaseModel

from application.ports.api.subjects_queries import SubjectFrequency


class DoiPrefixInfo(BaseModel):
    """Préfixe DOI rattaché à un éditeur (lecture seule, vient de la table `doi_prefixes`)."""

    prefix: str
    ra: str
    crossref_member_id: int | None = None


class PublisherListItem(BaseModel):
    id: int
    name: str
    openalex_id: str | None
    country: str | None
    doi_prefixes: list[DoiPrefixInfo]
    publisher_type: str
    journal_count: int
    pub_count: int


class PublisherListResponse(BaseModel):
    total: int
    page: int
    pages: int
    publishers: list[PublisherListItem]


class PublisherDetailResponse(BaseModel):
    """GET /api/publishers/{id} : profil complet pour la page publique /publishers/[id]."""

    id: int
    name: str
    openalex_id: str | None
    country: str | None
    doi_prefixes: list[DoiPrefixInfo]
    publisher_type: str
    journal_count: int
    pub_count: int


class JournalTypeCount(BaseModel):
    """Compteur de revues par `journal_type` pour un éditeur."""

    journal_type: str | None
    count: int


class DocTypeCount(BaseModel):
    """Compteur de publications par `doc_type` pour un éditeur."""

    doc_type: str | None
    count: int


class OaStatusCount(BaseModel):
    """Compteur de publications par `oa_status` pour un éditeur."""

    oa_status: str | None
    count: int


class PublishersFacetOption(BaseModel):
    """Option d'une facette du listing éditeurs : valeur + label + compte.

    Pour la facette `publisher_types`, `label` reprend
    `PUBLISHER_TYPE_LABELS_FR`. Pour `countries` (texte libre observé en
    base), `label` est égal à `value`. `count` est exclusif à la
    dimension (= filtre courant moins cette facette), même convention
    que les facettes journals.
    """

    value: str
    label: str
    count: int


class PublishersFacetsResponse(BaseModel):
    """Facettes dynamiques pour `/api/publishers` (2 dimensions)."""

    publisher_types: list[PublishersFacetOption]
    countries: list[PublishersFacetOption]


class PublisherDashboardResponse(BaseModel):
    """GET /api/publishers/{id}/dashboard : agrégats pour l'exploration visuelle.

    `journal_types` : distribution des types des revues de l'éditeur (qualifie
    son portfolio). `doc_types` / `oa_statuses` : distributions des publis
    rattachées via ses revues, utiles pour le repérage d'incohérences à venir.
    """

    total_publications: int
    journal_types: list[JournalTypeCount]
    doc_types: list[DocTypeCount]
    oa_statuses: list[OaStatusCount]


class PublisherQueries(Protocol):
    """Opérations de lecture sur les éditeurs."""

    def list_publishers(
        self,
        *,
        search: str | None,
        publisher_types: list[str],
        countries: list[str],
        with_pubs: bool,
        sort: str,
        page: int,
        per_page: int,
    ) -> PublisherListResponse: ...

    def publishers_facets(
        self,
        *,
        search: str | None,
        publisher_types: list[str],
        countries: list[str],
        with_pubs: bool,
    ) -> PublishersFacetsResponse: ...

    def get_publisher_detail(self, publisher_id: int) -> PublisherDetailResponse | None: ...

    def get_publisher_dashboard(self, publisher_id: int) -> PublisherDashboardResponse | None: ...

    def get_publisher_subjects(
        self, publisher_id: int, *, limit: int
    ) -> list[SubjectFrequency]: ...

    def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]: ...
