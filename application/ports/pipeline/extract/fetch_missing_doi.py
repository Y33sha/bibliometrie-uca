"""Port : adapter source-spécifique pour le fetch des DOI manquants.

Implémenté par `infrastructure.sources.<source>.fetch_missing_doi`
(hal, openalex, wos, scanr, crossref).

L'orchestrateur (`application.pipeline.extract.fetch_missing_doi.run_async`)
consomme ce Protocol pour piloter une boucle async commune à toutes les
sources.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

import httpx
from sqlalchemy import Connection

CrossImportDoisReader = Callable[[Any, str, bool], list[str]]
"""Signature : ``(conn, target, all_staged) -> list[doi]``.

Injecté dans `run_async` pour respecter l'étanchéité DDD : la couche
application ne doit pas importer infrastructure pour lire la liste des
DOI manquants.
"""


class AsyncFetchMissingDoiAdapter(Protocol):
    """Protocole source-spécifique consommé par `run_async`.

    Les attributs paramètrent la boucle (nom source, taille de lot,
    plafond de concurrence, délai par worker). Les méthodes encapsulent
    tout ce qui varie par source : HTTP async (`fetch_async` avec
    client httpx partagé) et insertion DB sync (`insert`, sérialisée
    par l'orchestrateur).
    """

    source_key: str  # "hal" | "openalex" | "wos" | "scanr" | "crossref"
    batch_size: int  # 1 pour un appel par DOI, >1 pour un appel groupé
    max_concurrent: int  # plafond asyncio.Semaphore — respect du rate-limit API
    request_delay_s: float  # pause par worker après chaque fetch (0 = pas de pause)

    def configure(self, conn: Connection) -> None:
        """Lit la config (URLs, credentials) depuis la base avant la boucle."""

    def fetch_async(
        self, client: httpx.AsyncClient, dois: list[str]
    ) -> Awaitable[Iterable[dict[str, Any]]]:
        """Interroge l'API pour un lot (1 à `batch_size` DOI) via le client
        async partagé. Retourne les records trouvés (vide si rien trouvé)."""

    def insert(self, conn: Connection, record: dict[str, Any]) -> bool:
        """Insère le record dans staging. Retourne True si nouveau, False
        si déjà présent (ON CONFLICT DO NOTHING) ou non inséré."""
