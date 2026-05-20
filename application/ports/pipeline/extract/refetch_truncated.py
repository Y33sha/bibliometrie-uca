"""Port : adapter OpenAlex pour le re-fetch des works tronqués à 100 auteurs.

Implémenté par
`infrastructure.sources.openalex.refetch_truncated.PgOpenalexRefetchAdapter`.

L'orchestrateur (`application.pipeline.extract.refetch_truncated.refetch`)
consomme ce Protocol pour piloter une boucle async qui appelle l'API
work-par-work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import Connection


@dataclass(frozen=True, slots=True)
class TruncatedWork:
    """Référence vers un work staging soupçonné d'être tronqué."""

    staging_id: int
    openalex_id: str


class OpenalexRefetchAdapter(Protocol):
    """Port refetch_truncated : config, lookup SQL, HTTP, UPDATE SQL."""

    max_concurrent: int  # plafond asyncio.Semaphore — respect du rate-limit API

    def configure(self, conn: Connection) -> None:
        """Lit la config (URL, auth) depuis la base avant la boucle."""

    def find_truncated(self, conn: Connection, *, limit: int | None = None) -> list[TruncatedWork]:
        """SELECT des works staging avec exactement 100 authorships."""

    async def fetch_work(
        self, client: httpx.AsyncClient, openalex_id: str
    ) -> dict[str, Any] | None:
        """Fetch un work individuel via l'API OpenAlex (auteurs complets)."""

    def update_raw_data(self, conn: Connection, staging_id: int, work: dict[str, Any]) -> None:
        """UPDATE staging.raw_data = nouveau work, processed = FALSE.

        Ne recalcule **pas** `raw_hash` (dissymétrie volontaire du
        mécanisme de préservation — cf. docstring de l'orchestrateur).
        """
