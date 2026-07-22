"""Port : lectures sur les revues (consommé par le router journals).

Implémenté par `infrastructure.queries.api.journals.PgJournalQueries`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from application.ports.api._common import FacetOption, PaginatedResponse
from application.ports.api.subjects_queries import SubjectFrequency
from domain.journals.journal import JournalType, OaModel

# Vocabulaire de tri de la liste des revues : le champ, puis le sens.
JournalSort = Literal[
    "title_asc", "title_desc", "publisher_asc", "publisher_desc", "pubs_asc", "pubs_desc"
]


@dataclass(frozen=True, slots=True)
class JournalFilters:
    """Filtres que la liste des revues et ses facettes honorent toutes deux.

    `journal_types` et `oa_models` sont multi-valués : une option cochée s'ajoute aux autres. `with_pubs` restreint aux revues portant au moins une publication.
    """

    search: str = ""
    publisher_id: int | None = None
    journal_types: list[str] = field(default_factory=list)
    is_in_doaj: bool | None = None
    oa_models: list[str] = field(default_factory=list)
    with_pubs: bool = False


class JournalOut(BaseModel):
    """Représentation d'une revue dans la liste paginée `/api/journals`.

    `pub_name` est joint depuis `publishers`, `pub_count` est un agrégat sur `publications` ; ni l'un ni l'autre ne sont des colonnes natives de la table `journals`.
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
    apc_amount: float | None
    apc_currency: str | None
    oa_model: OaModel | None
    journal_type: JournalType | None
    is_academic: bool | None
    doi_prefix: str | None
    pub_count: int
    doaj_url: str | None


class JournalListResponse(PaginatedResponse):
    journals: list[JournalOut]


class JournalDetailResponse(JournalOut):
    """GET /api/journals/{id} : profil complet de la revue pour sa page publique.

    Une ligne de liste, plus la réponse DOAJ brute et sa date d'import. Le payload est exposé tel quel : son exploration précède le choix des colonnes typées qu'on en tirerait.
    """

    doaj_payload: dict[str, Any] | None
    doaj_imported_at: datetime | None


class DocTypeCount(BaseModel):
    """Compteur de publications par `doc_type` pour une revue.

    `expected` est vrai si ce `doc_type` figure parmi les valeurs attendues pour le `journal_type` de la revue (`domain.journals.expected`), ce qui laisse le frontend signaler les autres.
    """

    doc_type: str | None
    count: int
    expected: bool


class OaStatusCount(BaseModel):
    """Compteur de publications par `oa_status` pour une revue.

    `expected` est vrai si ce `oa_status` figure parmi les valeurs attendues pour le `oa_model` de la revue (`domain.journals.expected`).
    """

    oa_status: str | None
    count: int
    expected: bool


class JournalsFacetsResponse(BaseModel):
    """Facettes de `/api/journals` sur trois dimensions.

    Chaque dimension écarte son propre filtre de la condition WHERE, de sorte que son décompte annonce le nombre de revues atteignables si l'option était cochée ou décochée. `label` reprend `JOURNAL_TYPE_LABELS_FR` ou `OA_MODEL_LABELS_FR` selon la dimension ; la facette DOAJ expose `Indexée` / `Non indexée`.
    """

    journal_types: list[FacetOption]
    oa_models: list[FacetOption]
    doaj: list[FacetOption]


class JournalDashboardResponse(BaseModel):
    """GET /api/journals/{id}/dashboard : distributions des publications d'une revue.

    Les compteurs sont bruts, `None` et `unknown` compris : c'est à l'œil que se repèrent les incohérences, par exemple des publications `article` dans une revue de type `proceedings`.

    `expected_doc_types` et `expected_oa_statuses` listent les valeurs attendues pour le `journal_type` et le `oa_model` de la revue (`domain.journals.expected`), affichées au-dessus de chaque tableau. Elles sont vides quand la revue ne porte pas la valeur correspondante, ou que celle-ci n'est pas mappée.
    """

    total_publications: int
    doc_types: list[DocTypeCount]
    oa_statuses: list[OaStatusCount]
    expected_doc_types: list[str]
    expected_oa_statuses: list[str]


class JournalQueries(Protocol):
    """Opérations de lecture sur les revues."""

    def list_journals(
        self, *, filters: JournalFilters, sort: JournalSort, page: int, per_page: int
    ) -> JournalListResponse: ...

    def journals_facets(self, *, filters: JournalFilters) -> JournalsFacetsResponse: ...

    def get_journal_detail(self, journal_id: int) -> JournalDetailResponse | None: ...

    def get_journal_dashboard(self, journal_id: int) -> JournalDashboardResponse | None: ...

    def get_journal_subjects(self, journal_id: int, *, limit: int) -> list[SubjectFrequency]: ...
