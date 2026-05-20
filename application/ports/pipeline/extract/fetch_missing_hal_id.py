"""Port : adapter HAL pour le fetch des entrées HAL manquantes.

Implémenté par
`infrastructure.sources.hal.fetch_missing_hal_id.PgHalFetchMissingAdapter`.

L'orchestrateur (`application.pipeline.extract.fetch_missing_hal_id`)
combine les références remontées par les trois lookups SQL (OpenAlex,
ScanR, NNT theses) et pilote la boucle async de fetch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import Connection


@dataclass(frozen=True, slots=True)
class HalIdRef:
    """Référence HAL repérée via une autre source mais absente de staging."""

    source: str  # "openalex" | "scanr"
    hal_id: str
    foreign_id: str  # openalex_id / scanr_id — uniquement pour le log
    landing_url: str | None = None  # OA only


@dataclass(frozen=True, slots=True)
class NntRef:
    """Thèse soutenue (NNT) sans document HAL associé."""

    nnt: str
    theses_id: str  # pour le log


class HalFetchMissingAdapter(Protocol):
    """Port fetch_missing_hal_id : config, lookups SQL, HTTP, inserts SQL."""

    max_concurrent: int  # plafond asyncio.Semaphore
    delay_s: float  # pause par worker après chaque fetch

    def configure(self, conn: Connection) -> None:
        """Lit la config (URL) depuis la base avant la boucle."""

    # ── Lookups SQL (refs manquantes) ──────────────────────────

    def find_halid_refs_from_openalex(self, conn: Connection) -> list[HalIdRef]:
        """halIds référencés par OpenAlex (primary_location ou external_ids->'hal_id')
        et absents de staging HAL.
        """

    def find_halid_refs_from_scanr(self, conn: Connection) -> list[HalIdRef]:
        """halIds référencés par ScanR (externalIds[type=hal] ou external_ids->'hal_id')
        et absents de staging HAL.
        """

    def find_nnt_refs_from_theses(self, conn: Connection) -> list[NntRef]:
        """NNT (thèses soutenues) sans document HAL associé."""

    # ── HTTP ───────────────────────────────────────────────────

    async def fetch_by_halid(self, client: httpx.AsyncClient, hal_id: str) -> dict[str, Any] | None:
        """Fetch un document HAL par halId. Retourne `None` si introuvable."""

    async def fetch_by_nnt(self, client: httpx.AsyncClient, nnt: str) -> dict[str, Any] | None:
        """Fetch un document HAL par NNT (thèse). Retourne `None` si introuvable."""

    # ── SQL (inserts) ──────────────────────────────────────────

    def insert_halid_result(
        self, conn: Connection, hal_id: str, doc: dict[str, Any] | None
    ) -> bool:
        """Insère le doc, ou marque `not_found=TRUE` si `doc is None`.

        Retourne True si le doc a été trouvé (inséré ou existant).
        """

    def insert_nnt_result(
        self, conn: Connection, nnt: str, doc: dict[str, Any] | None
    ) -> tuple[bool, bool]:
        """Insère le doc HAL trouvé par NNT.

        Retourne `(api_found, inserted)` : `api_found=True` si HAL a
        renvoyé un doc, `inserted=True` s'il a effectivement été ajouté
        (i.e. son halId n'était pas déjà en staging).
        """
