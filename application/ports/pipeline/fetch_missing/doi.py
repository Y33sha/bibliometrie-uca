"""Port : adapter source-spécifique pour le fetch des DOI manquants.

Implémenté par `infrastructure.sources.<source>.fetch_missing_doi`
(hal, openalex, wos, scanr, crossref).

L'orchestrateur (`application.pipeline.fetch_missing.doi.run_async`)
consomme ce Protocol pour piloter une boucle async commune à toutes les
sources.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import httpx2
from sqlalchemy import Connection

from domain.types import JsonValue

MissingDoisReader = Callable[[Connection, str], list[str]]
"""Signature : `(conn, target) -> list[doi]`.

La fonction elle-même (`infrastructure.pipeline.fetch_missing.doi.get_missing_dois`) est injectée dans `run_async` : la couche application ne dépend pas d'`infrastructure` pour lire la liste des DOI manquants.
"""

FailedDoiRecorder = Callable[[Connection, str, str, int], None]
"""Signature : `(conn, source, doi, retry_after_days) -> None`. Inscrit dans `failed_lookups` un DOI dont la source a confirmé l'absence."""


@dataclass(frozen=True, slots=True)
class DoiBatchResult:
    """Réponse d'une source à un lot de DOI : notices trouvées, et DOI dont la source a confirmé l'absence.

    Un DOI du lot présent dans aucune des deux listes attend le run suivant : la source était indisponible, ou sa réponse ne permet pas de conclure.
    """

    records: list[Mapping[str, JsonValue]] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)


class AsyncFetchMissingDoiAdapter(Protocol):
    """Protocole source-spécifique consommé par `run_async`.

    Les attributs paramètrent la boucle (nom source, taille de lot,
    plafond de concurrence, délai par worker). Les méthodes encapsulent
    tout ce qui varie par source : HTTP async (`fetch_async` avec
    client httpx2 partagé) et insertion DB sync (`insert`, sérialisée
    par l'orchestrateur).
    """

    source_key: str  # "hal" | "openalex" | "wos" | "scanr" | "crossref"
    batch_size: int  # 1 pour un appel par DOI, >1 pour un appel groupé
    max_concurrent: int  # plafond asyncio.Semaphore — respect du rate-limit API
    request_delay_s: float  # pause par worker après chaque fetch (0 = pas de pause)

    def configure(self, conn: Connection) -> None:
        """Lit la config (URLs, credentials) depuis la base avant la boucle."""

    def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> Awaitable[DoiBatchResult]:
        """Interroge l'API pour un lot (1 à `batch_size` DOI) via le client async partagé."""

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        """Insère le record dans staging. Retourne True si nouveau, False si déjà présent (ON CONFLICT DO NOTHING) ou non inséré. Ne commite pas : `run_async` commite par lot."""
