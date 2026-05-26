"""Port : lectures sur les revues (consommé par le router journals).

Implémenté par `infrastructure.queries.journals.PgJournalQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4 — les DTOs vivent dans le port qui les définit (zone neutre, à côté des Protocols).
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel

from application.ports.api.subjects_queries import SubjectFrequency


class JournalOut(BaseModel):
    """Représentation d'une revue dans la liste paginée `/api/journals`.

    `pub_name` est joint depuis `publishers`, `pub_count` est un agrégat
    sur `publications` ; ni l'un ni l'autre ne sont des colonnes natives
    de la table `journals`.
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
    pub_count: int
    doaj_url: str | None


class JournalListResponse(BaseModel):
    total: int
    page: int
    pages: int
    journals: list[JournalOut]


class JournalDetailResponse(BaseModel):
    """GET /api/journals/{id} : profil complet de la revue pour la page publique.

    Superset de `JournalOut` + payload DOAJ brut + date d'import DOAJ.
    Le payload est exposé tel quel pour permettre l'exploration en attendant
    qu'on en extraie des colonnes typées (Phase 4 du chantier publishers-journals).
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
    pub_count: int
    doaj_payload: dict[str, Any] | None
    doaj_imported_at: datetime | None
    doaj_url: str | None


class DocTypeCount(BaseModel):
    """Compteur de publications par `doc_type` pour une revue.

    `expected` est vrai si ce `doc_type` figure dans les valeurs attendues
    pour le `journal_type` de la revue (cf. `domain.journals.expected`).
    Permet au frontend de styler les inattendus en warning.
    """

    doc_type: str | None
    count: int
    expected: bool


class OaStatusCount(BaseModel):
    """Compteur de publications par `oa_status` pour une revue.

    `expected` est vrai si ce `oa_status` figure dans les valeurs attendues
    pour le `oa_model` de la revue (cf. `domain.journals.expected`).
    """

    oa_status: str | None
    count: int
    expected: bool


class JournalsFacetOption(BaseModel):
    """Option d'une facette du listing revues : valeur + label FR + compte.

    `label` reprend `JOURNAL_TYPE_LABELS_FR` / `OA_MODEL_LABELS_FR` côté
    `journal_type` / `oa_model` ; pour la facette DOAJ on expose `Indexée`
    / `Non indexée`. Le champ s'appelle `label` (pas `label_fr`) pour
    rester compatible avec le composable `useFacets` côté front
    (convention partagée avec les facettes publications). `count` est le
    nombre de revues qui matcheraient si on ne sélectionnait que cette
    option, en appliquant tous les autres filtres actifs (= compte
    exclusif à la dimension, comme les facettes publications).
    """

    value: str
    label: str
    count: int


class JournalsFacetsResponse(BaseModel):
    """Facettes dynamiques pour `/api/journals` (3 dimensions).

    Chaque dimension exclut son propre filtre de la condition WHERE, ce
    qui permet d'afficher le nombre de revues atteignables si l'option
    était (dé)cochée.
    """

    journal_types: list[JournalsFacetOption]
    oa_models: list[JournalsFacetOption]
    doaj: list[JournalsFacetOption]


class JournalDashboardResponse(BaseModel):
    """GET /api/journals/{id}/dashboard : agrégats de signalement pour l'exploration.

    Les distributions exposent les compteurs bruts (incluant `None` /
    `unknown`) pour faciliter le repérage d'incohérences à l'œil
    (ex. publis `article` sur un `journal_type=proceedings`).

    `expected_doc_types` / `expected_oa_statuses` listent les valeurs
    attendues pour les `journal_type` / `oa_model` de la revue (cf.
    `domain.journals.expected`). Servent à afficher la liste « Attendus »
    au-dessus de chaque tableau. Listes vides si la revue n'a pas de
    journal_type / oa_model renseigné, ou si la valeur n'est pas mappée.
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

    def existing_journal_ids(self, journal_ids: tuple[int, ...]) -> set[int]: ...
