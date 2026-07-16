"""Port : adapter source-spécifique pour le fetch des DOI manquants.

Implémenté par `infrastructure.sources.<source>.fetch_missing_doi`
(hal, openalex, wos, scanr, crossref).

L'orchestrateur (`application.pipeline.cross_imports.fetch_missing_doi.run_async`)
consomme ce Protocol pour piloter une boucle async commune à toutes les
sources.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

import httpx
from sqlalchemy import Connection

CrossImportDoisReader = Callable[[Connection, str], list[str]]
"""Signature : `(conn, target) -> list[doi]`.

La fonction elle-même (`infrastructure.sources.common.get_cross_import_dois`) est injectée dans `run_async` : la couche application ne dépend pas d'`infrastructure` pour lire la liste des DOI manquants.
"""

_NOT_FOUND_STATUS = "not_found"


def not_found_marker(doi: str) -> dict[str, Any]:
    """Sentinelle « DOI introuvable » émise par `fetch_async`.

    Un adapter émet ce marqueur (au lieu d'un record API) pour un DOI que
    la source a **confirmé** absent (réponse vide ou 404), par opposition à
    une erreur transitoire (réseau, timeout) où il retourne `[]` sans rien
    émettre. `insert()` mémorise le marqueur dans `doi_lookups` : `next_retry`
    daté (backoff) pour les sources non natives, `next_retry` NULL (définitif)
    pour les sources dont le DOI est l'identifiant natif. L'orchestrateur
    l'exclut du compteur `fetched`.
    """
    return {"_status": _NOT_FOUND_STATUS, "_doi": doi}


def is_not_found_marker(record: dict[str, Any]) -> bool:
    """True si `record` est une sentinelle `not_found_marker`."""
    return record.get("_status") == _NOT_FOUND_STATUS


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
        si déjà présent (ON CONFLICT DO NOTHING) ou non inséré. Ne commite
        pas : `run_async` commite par lot."""
