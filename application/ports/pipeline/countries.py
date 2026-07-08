"""Port : SQL de la phase countries (détection, suggestion, recalcul des caches).

Implémenté par `infrastructure.queries.pipeline.countries.PgCountryQueries`.
Utilisé par les orchestrateurs de `application.pipeline.countries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class SuggestEligibleCounts(NamedTuple):
    """Compteurs des adresses sans pays, pour le log de la passe de suggestion."""

    eligible: int  # pas encore tentées (suggested_countries IS NULL) — toujours traitées
    has_suggestion: int
    empty_attempted: int  # tentées sans match (`= []`) — retraitées en mode retry_empty
    too_short: int


class CountryQueries(Protocol):
    """Opérations SQL de la phase countries : détection du pays des adresses (par
    nom de pays ou de lieu), suggestion floue, et recalcul en cascade des caches
    dénormalisés (sa, sp, publications) à partir de `addresses.countries`."""

    # ── Recalcul des caches dénormalisés ───────────────────────────

    def refresh_sa_countries(self, conn: Connection) -> int: ...

    def refresh_address_source_countries(self, conn: Connection) -> int: ...

    def refresh_publication_countries(self, conn: Connection) -> int: ...

    def clear_countries_dirty(self, conn: Connection) -> None: ...

    # ── Détection par nom de pays (segment final de l'adresse) ─────

    def load_country_forms(self, conn: Connection) -> dict[str, str]: ...

    def fetch_addresses_missing_country_raw(
        self, conn: Connection
    ) -> list[tuple[int, str]]: ...

    # ── Détection par nom de lieu (institution, ville) ─────────────

    def load_place_forms(self, conn: Connection) -> dict[str, str]: ...

    def fetch_addresses_missing_country_normalized(
        self, conn: Connection
    ) -> list[tuple[int, str]]: ...

    # ── Suggestion floue (sous-chaîne dans le pool des adresses avec pays) ──

    def count_suggest_eligible(self, conn: Connection) -> SuggestEligibleCounts: ...

    def fetch_suggest_targets_chunk(
        self, conn: Connection, *, after_id: int, limit: int, retry_empty: bool = False
    ) -> list[tuple[int, str]]: ...

    def load_country_pool(self, conn: Connection) -> list[tuple[str, list[str]]]: ...

    # ── Écriture des pays détectés / suggérés ──────────────────────

    def write_countries(
        self,
        conn: Connection,
        rows: list[tuple[int, list[str]]],
        *,
        target_column: str = "suggested_countries",
    ) -> None: ...
