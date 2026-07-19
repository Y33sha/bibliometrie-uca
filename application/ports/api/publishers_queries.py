"""Port : lectures sur les éditeurs (consommé par le router publishers).

Implémenté par `infrastructure.queries.api.publishers.PgPublisherQueries`.
"""

from typing import Literal, Protocol

from pydantic import BaseModel

from application.ports.api._common import PaginatedResponse

# Vocabulaire de tri de la liste des éditeurs : le champ, puis le sens.
PublisherSort = Literal[
    "name_asc", "name_desc", "journals_asc", "journals_desc", "pubs_asc", "pubs_desc"
]
from application.ports.api.subjects_queries import SubjectFrequency


class DoiPrefixInfo(BaseModel):
    """Préfixe DOI rattaché à un éditeur (lecture seule, vient de la table `doi_prefixes`)."""

    prefix: str
    ra: str
    crossref_member_id: int | None = None


class Publisher(BaseModel):
    """Profil d'un éditeur, commun à la ligne de liste et à la page publique `/publishers/[id]`.

    `pub_count` compte les seules publications du périmètre, sommées sur les revues de l'éditeur.
    """

    id: int
    name: str
    openalex_id: str | None
    country: str | None
    doi_prefixes: list[DoiPrefixInfo]
    publisher_type: str
    journal_count: int
    pub_count: int


class PublisherListResponse(PaginatedResponse):
    publishers: list[Publisher]


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
        sort: PublisherSort,
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

    def get_publisher_detail(self, publisher_id: int) -> Publisher | None: ...

    def get_publisher_dashboard(self, publisher_id: int) -> PublisherDashboardResponse | None: ...

    def get_publisher_subjects(
        self, publisher_id: int, *, limit: int
    ) -> list[SubjectFrequency]: ...
