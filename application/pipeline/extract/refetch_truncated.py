"""Orchestrateur du re-fetch des works OpenAlex tronqués à 100 auteurs.

L'API OpenAlex bulk retourne max 100 authorships par work. Cet orchestrateur détecte les works avec exactement 100 auteurs dans le staging et les re-fetche individuellement via l'API (qui retourne alors tous les auteurs).

Implémentation async : pool de `adapter.max_concurrent` workers (`run_fetch_pool`) sur un client `httpx` partagé, pour respecter le plafond OpenAlex (~10 req/s).

**Préservation des authorships complètes.** Le refetch ne recalcule **pas** `raw_hash` (cf. adapter `update_raw_data`) : la ligne refetchée garde le hash du payload bulk initial. Tant que le bulk renvoie le même payload tronqué, son hash matchera celui en base et le document ne sera pas réimporté. Un changement bulk (raw_hash différent) écrasera raw_data avec la version tronquée, et le prochain passage du refetch dans le même run pipeline réimportera le document complet.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from sqlalchemy import Connection

from application.pipeline._fetch_pool import run_fetch_pool
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
    total = len(truncated)
    log.info(f"{total} works marqués tronqués (à vérifier/compléter)")

    metrics = PhaseMetrics(seen=total)
    if not truncated:
        log.info(
            "✓ refetch_truncated terminé en %.1fs — %s",
            time.perf_counter() - t0,
            metrics.as_summary(),
        )
        return metrics

    processed = 0

    async def _fetch(client: httpx.AsyncClient, ref: TruncatedWork) -> dict[str, Any] | None:
        return await adapter.fetch_work(client, ref.openalex_id)

    def _write(conn: Connection, ref: TruncatedWork, work: dict[str, Any] | None) -> None:
        nonlocal processed
        if not work:
            # Fetch échoué : on garde le flag → retry au prochain run (robuste à une indisponibilité OpenAlex / un 429).
            metrics.add(errors=1)
        elif len(work.get("authorships", [])) <= 100:
            # Genuine 100 (ou moins) : pas tronqué → on efface juste le flag, sans réécrire raw_data ni forcer une re-normalisation.
            adapter.clear_truncated(conn, ref.staging_id)
            metrics.add(already_complete=1)
        else:
            adapter.update_raw_data(conn, ref.staging_id, work)
            metrics.add(updated=1)
        processed += 1
        if processed % COMMIT_EVERY == 0 or processed == total:
            log.info(
                f"  {processed}/{total} — {metrics.updated} mis à jour, "
                f"{metrics.extras.get('already_complete', 0)} déjà complets"
            )

    await run_fetch_pool(
        truncated,
        conn,
        max_concurrent=adapter.max_concurrent,
        commit_every=COMMIT_EVERY,
        fetch=_fetch,
        write=_write,
    )

    log.info(
        "✓ refetch_truncated terminé en %.1fs — %s", time.perf_counter() - t0, metrics.as_summary()
    )
    return metrics


__all__ = ["refetch"]
