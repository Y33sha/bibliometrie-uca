"""Port : adapter HAL pour la phase extract.

Implémenté par `infrastructure.sources.hal.extract_hal.PgHalExtractAdapter`.

Regroupe en un seul Protocol :
- la lecture de config (URLs, collections, années à interroger)
- les appels HTTP à l'API HAL (Solr search API)
- les écritures SQL dans `staging`

Cette unification reflète l'usage : l'orchestrateur `HalExtractor`
consomme les trois aspects en série pour une même extraction.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Connection


@dataclass(frozen=True)
class HalExtractConfig:
    """Config d'extraction HAL chargée depuis la BDD."""

    base_url: str
    all_collections: Mapping[str, str]  # {code → label}, fusion périmètre + extra
    n_collections: int  # nombre de collections du périmètre
    n_extra: int  # nombre de collections extra ajoutées


class HalExtractAdapter(Protocol):
    """Port HAL : config, parsing/requête, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> HalExtractConfig: ...

    def get_years(self, conn: Connection, *, mode: str) -> list[int]: ...

    # ── Parsing & requête (pur, sans I/O) ──────────────────────
    # L'orchestrateur ne connaît ni la syntaxe Solr, ni les champs JSON
    # HAL, ni la pagination : il délègue ces savoirs adapter au port.

    def build_query(self, years: list[int] | None, since: str | None = None) -> str: ...

    def per_page_for(self, collection_code: str | None) -> int: ...

    def build_collections_fq(self, collection_codes: list[str]) -> str:
        """Filtre Solr `collCode_s:(…)` couvrant l'union des collections configurées."""
        ...

    def configured_collections(self, doc: dict[str, Any], configured: set[str]) -> list[str]:
        """Collections du périmètre du record : `collCode_s` ∩ collections configurées."""
        ...

    def extract_id(self, doc: dict[str, Any]) -> str: ...

    def extract_doi(self, doc: dict[str, Any]) -> str | None: ...

    # ── HTTP (l'adapter connaît la base_url via sa construction) ──

    def fetch_page_cursor(self, query: str, fq: str, cursor_mark: str) -> dict[str, Any]:
        """Une page Solr en pagination `cursorMark` (`cursor_mark="*"` au premier
        appel, puis le `nextCursorMark` de la réponse précédente)."""
        ...

    # ── SQL ────────────────────────────────────────────────────

    def upsert_work(
        self,
        conn: Connection,
        hal_id: str,
        doi: str | None,
        raw_data: dict[str, Any],
        hal_collections: list[str],
    ) -> tuple[bool, bool]:
        """UPSERT staging. Retourne `(inserted, changed)` : insertion réelle
        (`xmax = 0`) et contenu réécrit (hash distinct de l'ancien)."""
        ...
