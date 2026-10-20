"""Recherche dans theses.fr de la phase `fetch_missing` : tâche `fetch_missing.theses_by_nnt`.

NNT de thèses soutenues que d'autres sources contiennent (scanR, OpenAlex, HAL) et que le staging theses.fr n'a pas : thèses soutenues dans un autre établissement, liées au périmètre par un auteur, un directeur ou un membre du jury. Un seul worker, cadencé à `THESES_DELAY`, comme le moissonnage.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection, text

from domain.source_publications.external_ids import ExternalIdType
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import THESES_DELAY
from pipeline.ingestion.common.failed_lookups import pending_failed_lookup_sql, record_failed_lookup
from pipeline.ingestion.common.staging import upsert_staging
from pipeline.ingestion.theses.api import fetch_thesis
from pipeline.ingestion.theses.fields import extract_doi
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, rien_a_faire
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import progression

_COMMIT_EVERY = 50

_NNT = f"sp.external_ids ->> '{ExternalIdType.NNT}'"

_NNT_PENDING = pending_failed_lookup_sql(source_sql="'theses'", id_type="nnt", value_sql=_NNT)

_MISSING_NNTS_SQL = text(
    f"""
    SELECT DISTINCT {_NNT} AS nnt
    FROM source_publications sp
    WHERE sp.source <> 'theses'
      AND {_NNT} IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'theses' AND s.source_id = {_NNT}
      )
      AND NOT {_NNT_PENDING}
    ORDER BY 1
    """
)


def get_missing_nnts(conn: Connection, *, retry_after_days: int) -> list[str]:
    """NNT que des documents d'autres sources contiennent, absents du staging theses.fr. Écarte ceux déjà cherchés en vain : theses.fr attribue les NNT, l'échec est définitif."""
    return list(conn.execute(_MISSING_NNTS_SQL, {"retry_after_days": retry_after_days}).scalars())


async def fetch_missing_theses_by_nnt(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans theses.fr les thèses repérées par NNT dans d'autres sources et les écrit dans `staging`.

    Un NNT introuvable est inscrit dans `failed_lookups` et cherché de nouveau après `retry_after_days` jours. theses.fr indisponible laisse le NNT de côté, sans comptage : il reste dans la sélection du run suivant.

    `total` = NNT à chercher, `new` = documents insérés, `extras["not_found"]` = NNT introuvables.
    """
    nnts = get_missing_nnts(conn, retry_after_days=retry_after_days)
    metrics = PhaseMetrics(seen=len(nnts))
    if not nnts:
        rien_a_faire(log)
        return metrics

    async def _fetch(
        client: httpx2.AsyncClient, nnt: str
    ) -> LookupOutcome[Mapping[str, JsonValue]]:
        fetched = await fetch_thesis(client, nnt)
        await asyncio.sleep(THESES_DELAY)
        return fetched

    with progression(
        len(nnts), f"{DERNIERE_BRANCHE}theses.fr", log, compte_retenus=True
    ) as avancement:

        def _write(
            conn: Connection, nnt: str, result: LookupOutcome[Mapping[str, JsonValue]]
        ) -> None:
            if isinstance(result, NotFound):
                record_failed_lookup(conn, "theses", "nnt", nnt)
                metrics.add(not_found=1)
            elif not isinstance(result, Unavailable):
                inserted, _ = upsert_staging(
                    conn,
                    source="theses",
                    source_id=nnt,
                    doi=extract_doi(result),
                    raw_data=result,
                    entry_mode=StagingEntryMode.FETCH_MISSING_THESES,
                )
                if inserted:
                    metrics.add(new=1)
                    avancement.retient()
            avancement.avance()

        await run_fetch_pool(
            nnts,
            conn,
            max_concurrent=1,
            commit_every=_COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
        )
    return metrics
