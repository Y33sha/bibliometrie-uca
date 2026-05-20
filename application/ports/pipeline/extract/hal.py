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
    all_collections: Mapping[str, str]  # {code → label}, fusion labos + extra
    n_collections: int  # nombre de collections labo
    n_extra: int  # nombre de collections extra ajoutées


class HalExtractAdapter(Protocol):
    """Port HAL : config, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> HalExtractConfig: ...

    def get_years(self, conn: Connection, *, mode: str) -> list[int]: ...

    # ── HTTP (l'adapter connaît la base_url via sa construction) ──

    def fetch_collection_ids(self, query: str, collection_code: str) -> list[str]: ...

    def fetch_single_work(self, hal_id: str) -> dict[str, Any] | None: ...

    def fetch_page(self, query: str, collection_code: str, start: int) -> dict[str, Any]: ...

    # ── SQL ────────────────────────────────────────────────────

    def upsert_work(
        self,
        conn: Connection,
        hal_id: str,
        doi: str | None,
        raw_data: dict[str, Any],
        collection: str,
    ) -> None: ...

    def tag_existing_with_collection(
        self, conn: Connection, hal_ids: list[str], collection_code: str
    ) -> int: ...
