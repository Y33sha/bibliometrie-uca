"""Orchestrateur du fetch des DOI manquants dans une source cible.

Pour chaque DOI présent dans d'autres sources mais absent de la cible,
interroge l'API de la cible et insère le record dans staging.

Le comportement spécifique à chaque source (endpoint, auth, format de
requête/réponse, SQL d'insertion) est délégué à un adapter qui implémente
`AsyncFetchMissingDoiAdapter`.

Implémentation async (`httpx.AsyncClient` + `asyncio.Semaphore` par
source) pour saturer les rate-limits autorisés. Sur OpenAlex on
mesure environ 18 req/s, soit ×3-4 par rapport à un appel séquentiel
respectant le même quota.

La lecture de la liste des DOI manquants (requête SQL) est injectée en
tant que callable ``CrossImportDoisReader`` pour respecter l'étanchéité
DDD : la couche application ne doit pas importer infrastructure.

Utilisé par la phase `fetch_missing_doi` du pipeline, une fois par source
cible (hal, openalex, wos, scanr).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

import httpx

CrossImportDoisReader = Callable[[Any, str, bool], list[str]]
"""Signature : ``(conn, target, all_staged) -> list[doi]``."""


class AsyncFetchMissingDoiAdapter(Protocol):
    """Protocole source-spécifique utilisé par `run_async()`.

    Les attributs paramètrent la boucle (nom source, taille de lot,
    plafond de concurrence). Les méthodes encapsulent tout ce qui varie
    par source : HTTP async (`fetch_async` avec client httpx partagé)
    et insertion DB sync (`insert`, sérialisée par l'orchestrateur).
    """

    source_key: str  # "hal" | "openalex" | "wos" | "scanr"
    batch_size: int  # 1 pour un appel par DOI, >1 pour un appel groupé
    max_concurrent: int  # plafond asyncio.Semaphore — respect du rate-limit API
    request_delay_s: float  # pause par worker après chaque fetch (0 = pas de pause)

    def configure(self, cur: Any) -> None:
        """Lit la config (URLs, credentials) depuis la base avant la boucle."""

    def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Awaitable[Iterable[dict]]:
        """Interroge l'API pour un lot (1 à `batch_size` DOI) via le client
        async partagé. Retourne les records trouvés (vide si rien trouvé)."""

    def insert(self, conn: Any, record: dict) -> bool:
        """Insère le record dans staging. Retourne True si nouveau, False
        si déjà présent (ON CONFLICT DO NOTHING) ou non inséré."""


async def run_async(
    conn: Any,
    adapter: AsyncFetchMissingDoiAdapter,
    log: logging.Logger,
    *,
    cross_import_dois_reader: CrossImportDoisReader,
    all_staged: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Boucle principale : missing DOIs → fetch async → insert.

    Lance les fetchs HTTP en parallèle via `asyncio.gather`, bornés par
    un sémaphore `adapter.max_concurrent` pour respecter le rate-limit
    de l'API. Les inserts DB restent sync, délégués au threadpool via
    `asyncio.to_thread` et sérialisés par un `asyncio.Lock` (la conn
    psycopg sync n'est pas thread-safe).

    Args:
        conn: connexion psycopg ouverte.
        adapter: instance source-spécifique async.
        log: logger.
        cross_import_dois_reader: callable qui lit en base les DOI
            présents dans d'autres sources et absents de la cible.
        all_staged: si False, ne considère que les DOI issus de rows
            `processed=FALSE` dans les autres sources.
        dry_run: compte et log sans fetch ni insert.
        limit: nombre max de DOI à traiter.

    Returns:
        Stats {dois, fetched, inserted}.
    """
    cur = conn.cursor()
    adapter.configure(cur)
    cur.close()

    dois = cross_import_dois_reader(conn, adapter.source_key, all_staged)
    log.info("%d DOI manquants pour %s", len(dois), adapter.source_key)

    if limit:
        dois = dois[:limit]
        log.info("Limité à %d DOI", len(dois))

    if dry_run:
        log.info("Dry-run — rien inséré.")
        return {"dois": len(dois), "fetched": 0, "inserted": 0}

    total = len(dois)
    if total == 0:
        return {"dois": 0, "fetched": 0, "inserted": 0}

    batches = [dois[i : i + adapter.batch_size] for i in range(0, total, adapter.batch_size)]

    sem = asyncio.Semaphore(adapter.max_concurrent)
    # Sérialise les inserts : la conn psycopg sync n'est pas thread-safe,
    # or `asyncio.to_thread` exécute dans un ThreadPoolExecutor partagé.
    db_lock = asyncio.Lock()
    progress = {"processed": 0, "fetched": 0, "inserted": 0}

    async with httpx.AsyncClient() as client:
        request_delay = getattr(adapter, "request_delay_s", 0.0)

        async def process_batch(batch: list[str], batch_idx: int) -> None:
            async with sem:
                try:
                    records = list(await adapter.fetch_async(client, batch))
                except Exception as e:
                    log.error("Erreur sur lot %d (%d DOI) : %s", batch_idx, len(batch), e)
                    records = []
                if request_delay:
                    await asyncio.sleep(request_delay)

            progress["fetched"] += len(records)
            for record in records:
                try:
                    async with db_lock:
                        inserted_one = await asyncio.to_thread(adapter.insert, conn, record)
                    if inserted_one:
                        progress["inserted"] += 1
                except Exception as e:
                    log.warning("Erreur insertion (%s) : %s", adapter.source_key, e)

            progress["processed"] += len(batch)
            if progress["processed"] % 100 == 0 or progress["processed"] >= total:
                log.info(
                    "  %d/%d — %d trouvés, %d insérés",
                    progress["processed"],
                    total,
                    progress["fetched"],
                    progress["inserted"],
                )

        await asyncio.gather(*(process_batch(b, i) for i, b in enumerate(batches)))

    log.info(
        "Terminé %s : %d DOI, %d trouvés, %d insérés",
        adapter.source_key,
        total,
        progress["fetched"],
        progress["inserted"],
    )
    return {"dois": total, "fetched": progress["fetched"], "inserted": progress["inserted"]}
