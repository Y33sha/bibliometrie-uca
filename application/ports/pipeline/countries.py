"""Port : SQL de la phase countries (détection, suggestion, recalcul des caches).

Implémenté par `infrastructure.queries.pipeline.countries.PgCountryQueries`, utilisé par les orchestrateurs de `application.pipeline.countries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class SuggestEligibleCounts(NamedTuple):
    """Compteurs des adresses sans pays, pour le log de la passe de suggestion."""

    eligible: int  # aucune suggestion tentée
    has_suggestion: int
    empty_attempted: int  # tentées sans match (`= []`) — retraitées en mode retry_empty


class AddressCountryStatus(NamedTuple):
    """Bilan de l'état pays des adresses (restreint à `pub_count > 0`)."""

    total: int
    with_country: int
    with_suggestion: int
    none: int


class CountryQueries(Protocol):
    """Opérations SQL de la phase countries : détection du pays des adresses (par nom de pays ou de lieu), suggestion floue, et recalcul des caches dénormalisés (source_publications, publications) à partir de `addresses.countries`."""

    # ── Bilan (début / fin de phase) ───────────────────────────────

    def count_address_country_status(self, conn: Connection) -> AddressCountryStatus:
        """Bilan de la résolution des pays sur les adresses utiles (`pub_count > 0`)."""
        ...

    # ── Recalcul des caches dénormalisés ───────────────────────────

    def refresh_address_source_countries(self, conn: Connection) -> int:
        """Recalcule `source_publications.countries` — union des pays des adresses des `source_authorships` du document — sur les documents qu'un flag `countries_dirty` signale. Retourne le nombre de lignes modifiées."""
        ...

    def refresh_publication_countries(self, conn: Connection) -> int:
        """Recalcule `publications.countries` — union des `source_publications.countries` de la publication — sur les publications qu'un flag `countries_dirty` signale. Retourne le nombre de lignes modifiées."""
        ...

    def clear_countries_dirty(self, conn: Connection) -> None:
        """Purge les flags `countries_dirty` (`source_authorships` et `addresses`) en fin de cascade."""
        ...

    # ── Détection par nom de pays (segment final de l'adresse) ─────

    def load_country_forms(self, conn: Connection) -> dict[str, str]:
        """Formes normalisées des noms de pays, chacune avec le code ISO du pays qu'elle désigne : `{forme: code ISO}`."""
        ...

    def fetch_addresses_missing_country_raw(self, conn: Connection) -> list[tuple[int, str]]:
        """`(id, raw_text)` des adresses sans pays. La détection par nom de pays lit le texte brut, dont le segment final porte le pays."""
        ...

    # ── Détection par nom de lieu (institution, ville) ─────────────

    def load_place_forms(self, conn: Connection) -> dict[str, str]:
        """Formes normalisées des noms d'institutions et de villes, chacune avec le code ISO du pays où le lieu se situe : `{forme: code ISO}`."""
        ...

    def fetch_addresses_missing_country_normalized(self, conn: Connection) -> list[tuple[int, str]]:
        """`(id, normalized_text)` des adresses sans pays, pour la détection par nom de lieu."""
        ...

    # ── Suggestion floue (sous-chaîne dans le pool des adresses avec pays) ──

    def count_suggest_eligible(self, conn: Connection) -> SuggestEligibleCounts:
        """Compte les adresses sans pays selon ce que la passe de suggestion en fait : à traiter, déjà suggérées, déjà tentées sans match. Les trois ensembles partitionnent les adresses sans pays."""
        ...

    def fetch_suggest_targets_chunk(
        self, conn: Connection, *, after_id: int, limit: int, retry_empty: bool = False
    ) -> list[tuple[int, str]]:
        """Tranche `(id, normalized_text)` des adresses à suggérer, paginée par keyset sur `after_id`. `retry_empty` y joint les adresses tentées sans match, au cas où le pool aurait grossi entre deux runs. Liste vide = parcours terminé."""
        ...

    def load_country_pool(self, conn: Connection) -> list[tuple[str, list[str]]]:
        """Pool de référence de la suggestion : `(normalized_text, countries)` des adresses ayant un pays. Tenu en mémoire, rescanné à chaque batch de cibles."""
        ...

    # ── Écriture des pays détectés / suggérés ──────────────────────

    def write_countries(
        self,
        conn: Connection,
        rows: list[tuple[int, list[str]]],
        *,
        target_column: str = "suggested_countries",
    ) -> None:
        """Écrit en bloc les `(address_id, codes ISO)` de `rows` dans la colonne `target_column` d'`addresses` : `countries` (pays retenus) ou `suggested_countries` (suggestions, `[]` = tentée sans match). Idempotent.

        Écrire `countries` pose aussi `countries_dirty` sur les lignes touchées : le refresh des caches en dérive les documents à recalculer.
        """
        ...
