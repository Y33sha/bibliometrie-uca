"""Port : adapter HAL pour le fetch des entrées HAL manquantes.

Implémenté par `infrastructure.sources.hal.fetch_missing_hal.PgHalFetchMissingAdapter`. Les orchestrateurs de `application.pipeline.fetch_missing.hal` le consomment : `fetch_missing_hal_by_id` pour les hal-ids repérés dans d'autres sources, `fetch_missing_hal_by_nnt` pour les NNT de theses.fr.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple, Protocol

import httpx2
from sqlalchemy import Connection

from domain.types import JsonValue


class NntInsertResult(NamedTuple):
    """Issue d'`insert_nnt_result` : HAL a-t-il renvoyé un doc, et a-t-il été ajouté au staging."""

    api_found: bool
    inserted: bool


class HalFetchMissingAdapter(Protocol):
    """Port fetch_missing_hal : config, lookups SQL, HTTP, inserts SQL."""

    max_concurrent: int  # plafond asyncio.Semaphore
    delay_s: float  # pause par worker après chaque fetch

    def configure(self, conn: Connection) -> None:
        """Lit la config (URL) depuis la base avant la boucle."""

    # ── Lookups SQL (identifiants manquants) ───────────────────

    def find_missing_hal_ids(self, conn: Connection) -> list[str]:
        """hal-ids portés par les publications in-périmètre d'OpenAlex et de ScanR, absents du staging HAL."""

    def find_missing_nnts(self, conn: Connection) -> list[str]:
        """NNT des thèses soutenues sans document HAL associé."""

    # ── HTTP ───────────────────────────────────────────────────

    async def fetch_by_halid(
        self, client: httpx2.AsyncClient, hal_id: str
    ) -> Mapping[str, JsonValue] | None:
        """Fetch un document HAL par halId. Retourne `None` si introuvable."""

    async def fetch_by_nnt(
        self, client: httpx2.AsyncClient, nnt: str
    ) -> Mapping[str, JsonValue] | None:
        """Fetch un document HAL par NNT (thèse). Retourne `None` si introuvable."""

    # ── SQL (inserts) ──────────────────────────────────────────

    def insert_halid_result(
        self, conn: Connection, hal_id: str, doc: Mapping[str, JsonValue] | None
    ) -> bool:
        """Insère le doc, ou marque `not_found_at` si `doc is None`.

        Retourne True si le doc a été trouvé (inséré ou existant).
        """

    def insert_nnt_result(
        self, conn: Connection, nnt: str, doc: Mapping[str, JsonValue] | None
    ) -> NntInsertResult:
        """Insère le doc HAL trouvé par NNT. `inserted` est faux si son halId était déjà en staging."""
