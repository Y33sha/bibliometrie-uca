"""Port : SQL de la phase countries (détection, suggestion, recalcul des caches).

Implémenté par `infrastructure.pipeline.countries.PgCountryQueries`, utilisé par les orchestrateurs de `application.pipeline.countries`.
"""

from dataclasses import dataclass
from typing import NamedTuple, Protocol

from sqlalchemy import Connection


@dataclass(frozen=True, slots=True)
class AddressCountryFilter:
    """Critères de sélection d'adresses pour une attribution de pays en masse.

    Combinés en AND. `search` : sous-chaîne cherchée dans `raw_text` (ILIKE, insensible à la casse et aux accents). `has_country` : True → `countries` renseigné, False → NULL, None → critère inactif. `country_code` / `suggested_country` : code présent dans la colonne correspondante."""

    search: str | None = None
    has_country: bool | None = None
    country_code: str | None = None
    suggested_country: str | None = None

    @property
    def is_empty(self) -> bool:
        """Vrai si aucun critère n'est renseigné."""
        return not (
            self.search
            or self.has_country is not None
            or self.country_code
            or self.suggested_country
        )


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
    """Opérations SQL ensemblistes sur les pays des adresses : la phase countries (détection par nom de pays ou de lieu, suggestion floue, recalcul des caches dénormalisés `source_publications` / `publications`) et l'attribution manuelle admin (ajout par lot, propagation horizontale et verticale)."""

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

    # ── Formes de noms (pays, lieux) et adresses à résoudre ───────

    def load_country_forms(self, conn: Connection) -> dict[str, str]:
        """Formes normalisées des noms de pays, chacune avec le code ISO du pays qu'elle désigne : `{forme: code ISO}`."""
        ...

    def load_place_forms(self, conn: Connection) -> dict[str, str]:
        """Formes normalisées des noms d'institutions et de villes, chacune avec le code ISO du pays où le lieu se situe : `{forme: code ISO}`."""
        ...

    def fetch_addresses_missing_country_normalized(self, conn: Connection) -> list[tuple[int, str]]:
        """`(id, normalized_text)` des adresses sans pays, pour les détections par nom (pays en fin d'adresse, ou lieu)."""
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

    # ── Attribution manuelle et propagation (admin) ────────────────

    def batch_add_country_by_ids(
        self, conn: Connection, country_code: str, address_ids: list[int]
    ) -> list[int]:
        """Ajoute `country_code` aux `countries` des adresses données, sans doublon ni écrasement des codes déjà posés. Retourne les ids atteints."""
        ...

    def batch_add_country_by_filter(
        self, conn: Connection, country_code: str, criteria: AddressCountryFilter
    ) -> list[int]:
        """Comme `batch_add_country_by_ids`, sur les adresses retenues par `criteria`. Retourne les ids modifiés ; critères tous vides : aucune écriture, `[]`."""
        ...

    def propagate_countries_across_similar_addresses(
        self, conn: Connection, source_ids: list[int]
    ) -> list[int]:
        """Propage `countries` depuis les adresses `source_ids` vers celles qui partagent leur `normalized_text` et portent un `countries` différent (ou NULL). Retourne les ids propagés ; `source_ids` vide : `[]`. La source doit avoir un `countries` non NULL."""
        ...

    def refresh_source_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `source_publications.countries` (union des pays des adresses de leurs signatures) pour les documents rattachés à l'une des `address_ids`. Idempotent. Retourne le nombre de documents mis à jour."""
        ...

    def refresh_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `publications.countries` (union des `source_publications.countries`) pour les publications rattachées à l'une des `address_ids`. Idempotent. Retourne le nombre de publications mises à jour."""
        ...
