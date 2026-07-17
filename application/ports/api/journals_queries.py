"""Port : lectures sur les revues (consommé par le router journals).

Implémenté par `infrastructure.queries.api.journals.PgJournalQueries`.
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel

from application.ports.api._common import PaginatedResponse
from application.ports.api.subjects_queries import SubjectFrequency
from domain.journals.journal import JournalType


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
    oa_model: str | None
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


class JournalsFacetOption(BaseModel):
    """Option d'une facette de la liste des revues : valeur, libellé français et compte.

    `label` reprend `JOURNAL_TYPE_LABELS_FR` ou `OA_MODEL_LABELS_FR` selon la dimension ; la facette DOAJ expose `Indexée` / `Non indexée`. Le champ se nomme `label` et non `label_fr` pour le composable `useFacets` du frontend, convention partagée avec les facettes des publications.

    `count` est le nombre de revues atteignables si cette seule option était cochée, les autres filtres actifs restant appliqués.
    """

    value: str
    label: str
    count: int


class JournalsFacetsResponse(BaseModel):
    """Facettes de `/api/journals` sur trois dimensions.

    Chaque dimension écarte son propre filtre de la condition WHERE, de sorte que son décompte annonce le nombre de revues atteignables si l'option était cochée ou décochée.
    """

    journal_types: list[JournalsFacetOption]
    oa_models: list[JournalsFacetOption]
    doaj: list[JournalsFacetOption]


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
        self,
        *,
        search: str | None,
        publisher_id: int | None,
        journal_types: list[str],
        is_in_doaj: bool | None,
        oa_models: list[str],
        with_pubs: bool,
        sort: str,
        page: int,
        per_page: int,
    ) -> JournalListResponse: ...

    def journals_facets(
        self,
        *,
        search: str | None,
        publisher_id: int | None,
        journal_types: list[str],
        is_in_doaj: bool | None,
        oa_models: list[str],
        with_pubs: bool,
    ) -> JournalsFacetsResponse: ...

    def get_journal_detail(self, journal_id: int) -> JournalDetailResponse | None: ...

    def get_journal_dashboard(self, journal_id: int) -> JournalDashboardResponse | None: ...

    def get_journal_subjects(self, journal_id: int, *, limit: int) -> list[SubjectFrequency]: ...
