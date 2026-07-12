"""Orchestrateur du re-fetch des works OpenAlex tronqués à 100 auteurs.

L'API OpenAlex bulk retourne max 100 authorships par work. Cet orchestrateur détecte les works avec exactement 100 auteurs dans le staging et les re-fetche individuellement via l'API (qui retourne alors tous les auteurs).

Implémentation async : `httpx.AsyncClient` partagé + `asyncio.Semaphore(adapter.max_concurrent)` pour respecter le plafond OpenAlex (~10 req/s, cf. `fetch_missing_doi`).

**Préservation des authorships complètes.** Le refetch ne recalcule **pas** `raw_hash` (cf. adapter `update_raw_data`) : la ligne refetchée garde le hash du payload bulk initial. Tant que le bulk renvoie le même payload tronqué, son hash matchera celui en base et le document ne sera pas réimporté. Un changement bulk (raw_hash différent) écrasera raw_data avec la version tronquée, et le prochain passage du refetch dans le même run pipeline réimportera le document complet.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.refetch_truncated import (
    OpenalexRefetchAdapter,
    TruncatedWork,
)

COMMIT_EVERY = 50


async def refetch(
    conn: Connection,
    adapter: OpenalexRefetchAdapter,
    log: logging.Logger,
) -> PhaseMetrics:
    """Re-fetch les works OpenAlex marqués `staging.authors_truncated`.

    `updated` compte les works ré-écrits ; `already_complete` (extras) ceux qui avaient pile 100 auteurs (genuine, flag effacé) ; `errors` les fetchs échoués.
    """
    log.info("▶ refetch_truncated")
    t0 = time.perf_counter()
    adapter.configure(conn)

    truncated = adapter.find_truncated(conn)
    log.info(f"{len(truncated)} works marqués tronqués (à vérifier/compléter)")

    metrics = PhaseMetrics(seen=len(truncated))
    if not truncated:
        log.info(
            "✓ refetch_truncated terminé en %.1fs — %s",
            time.perf_counter() - t0,
            metrics.as_summary(),
        )
        return metrics

    sem = asyncio.Semaphore(adapter.max_concurrent)
    # La `Connection` SA sync n'est pas thread-safe ; les writes concurrents d'un paquet passent par `to_thread` sous ce lock (le commit se fait à la frontière de paquet, hors concurrence).
    db_lock = asyncio.Lock()

    async with httpx.AsyncClient() as client:

        async def process_one(ref: TruncatedWork) -> None:
            async with sem:
                work = await adapter.fetch_work(client, ref.openalex_id)

            if not work:
                # Fetch échoué : on garde le flag → retry au prochain run (robuste à une indisponibilité OpenAlex / un 429).
                metrics.add(errors=1)
            elif len(work.get("authorships", [])) <= 100:
                # Genuine 100 (ou moins) : pas tronqué → on efface juste le flag, sans réécrire raw_data ni forcer une re-normalisation.
                async with db_lock:
                    await asyncio.to_thread(adapter.clear_truncated, conn, ref.staging_id)
                metrics.add(already_complete=1)
            else:
                async with db_lock:
                    await asyncio.to_thread(adapter.update_raw_data, conn, ref.staging_id, work)
                metrics.add(updated=1)

        # Traitement par paquets : chaque paquet part en concurrence (débit borné par `sem`) puis est committé.
        for start in range(0, len(truncated), COMMIT_EVERY):
            chunk = truncated[start : start + COMMIT_EVERY]
            await asyncio.gather(*(process_one(ref) for ref in chunk))
            await asyncio.to_thread(conn.commit)
            done = min(start + COMMIT_EVERY, len(truncated))
            log.info(
                f"  {done}/{len(truncated)} — {metrics.updated} mis à jour, "
                f"{metrics.extras.get('already_complete', 0)} déjà complets"
            )
    log.info(
        "✓ refetch_truncated terminé en %.1fs — %s", time.perf_counter() - t0, metrics.as_summary()
    )
    return metrics


__all__ = ["refetch"]
