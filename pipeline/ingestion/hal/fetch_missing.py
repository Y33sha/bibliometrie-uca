"""Recherches dans HAL de la phase `fetch_missing`.

- `fetch_missing_hal_by_id` (tâche `fetch_missing.hal_by_id`) : hal-ids portés par des documents OpenAlex et ScanR, absents du staging HAL ; requête Solr `halId_s`.
- `fetch_missing_hal_by_nnt` (tâche `fetch_missing.hal_by_nnt`) : NNT de thèses soutenues sans document HAL ; requête Solr `nntId_s`. Réservé au mode `full`.
- `HalDoiSearch` (tâche `fetch_missing.doi.hal`) : recherche par DOI, pilotée par `pipeline.ingestion.common.doi_search`.

Les deux premières tournent sur un pool de `HAL_MAX_CONCURRENT` workers, avec des écritures séquentielles et un commit tous les `_COMMIT_EVERY` identifiants.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence

import httpx2
from sqlalchemy import Connection, text

from domain.source_records.external_ids import ExternalIdType
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import HAL_DELAY
from pipeline.ingestion.common.doi_search import DoiBatchResult
from pipeline.ingestion.common.failed_lookups import (
    LookupIdType,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.common.staging import StagingStore, UpsertOutcome
from pipeline.ingestion.hal.api import search_one
from pipeline.runtime.observability.log_format import LAST_BRANCH, nothing_to_do
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress

# HAL ne publie pas de seuil officiel : 5 workers et une pause de HAL_DELAY par worker donnent ~6-7 req/s, sans rafale.
HAL_MAX_CONCURRENT = 5

_COMMIT_EVERY = 50

_HAL_ID_PENDING = pending_failed_lookup_sql(
    source_sql="'hal'", id_type="hal_id", value_sql="h.hal_id"
)

_MISSING_HAL_IDS_SQL = text(
    f"""
    SELECT DISTINCT h.hal_id
    FROM source_records sr
    JOIN publications p ON p.id = sr.publication_id
    CROSS JOIN LATERAL jsonb_array_elements_text(sr.external_ids -> '{ExternalIdType.HAL_ID}') AS h(hal_id)
    WHERE sr.source IN ('openalex', 'scanr')
      AND p.in_perimeter
      AND jsonb_typeof(sr.external_ids -> '{ExternalIdType.HAL_ID}') = 'array'
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'hal' AND s.source_id = h.hal_id
      )
      AND NOT {_HAL_ID_PENDING}
    """
)

_NNT_PENDING = pending_failed_lookup_sql(
    source_sql="'hal'", id_type="nnt", value_sql=f"sr.external_ids ->> '{ExternalIdType.NNT}'"
)

_MISSING_NNTS_SQL = text(
    f"""
    SELECT sr.external_ids ->> '{ExternalIdType.NNT}' AS nnt
    FROM source_records sr
    JOIN publications p ON p.id = sr.publication_id
    WHERE sr.source = 'theses'
      AND p.in_perimeter
      AND sr.external_ids ->> '{ExternalIdType.NNT}' IS NOT NULL
      AND p.doc_type != 'ongoing_thesis'
      AND NOT EXISTS (
          SELECT 1 FROM source_records hal
          WHERE hal.publication_id = p.id AND hal.source = 'hal'
      )
      AND NOT EXISTS (
          SELECT 1 FROM source_records hal
          WHERE hal.source = 'hal' AND hal.external_ids ->> '{ExternalIdType.NNT}' = sr.external_ids ->> '{ExternalIdType.NNT}'
      )
      AND NOT {_NNT_PENDING}
    """
)


def get_missing_hal_ids(conn: Connection, *, retry_after_days: int) -> list[str]:
    """hal-ids que des `source_records` OpenAlex ou ScanR portent dans `external_ids.hal_id`, absents du staging HAL.

    Seules comptent les publications in-périmètre : un document hors périmètre n'entraîne aucune recherche dans HAL. La sélection lit les `source_records` du run précédent : les documents extraits pendant le run y entrent au run suivant.

    Écarte les hal-ids déjà cherchés en vain : HAL attribue les hal-ids, l'échec est définitif.
    """
    return list(
        conn.execute(_MISSING_HAL_IDS_SQL, {"retry_after_days": retry_after_days}).scalars()
    )


def get_missing_nnts(conn: Connection, *, retry_after_days: int) -> list[str]:
    """NNT des `source_records` theses.fr des publications in-périmètre, hors thèses en cours, dont la publication n'a aucune `source_records` HAL.

    Écarte les NNT qu'un document HAL contient déjà, et ceux cherchés en vain il y a moins de `retry_after_days` jours.
    """
    return list(conn.execute(_MISSING_NNTS_SQL, {"retry_after_days": retry_after_days}).scalars())


def _stage(conn: Connection, doc: Mapping[str, JsonValue]) -> bool:
    """Écrit un document HAL dans `staging`. Rend `True` sur une insertion."""
    staged = StagingStore(conn).stage("hal", doc, entry_mode=StagingEntryMode.FETCH_MISSING_HAL)
    return staged is UpsertOutcome.NEW


async def _fetch_ids(
    conn: Connection,
    log: logging.Logger,
    ids: Sequence[str],
    *,
    fetch_one: Callable[
        [httpx2.AsyncClient, str], Awaitable[LookupOutcome[Mapping[str, JsonValue]]]
    ],
    id_type: LookupIdType,
) -> PhaseMetrics:
    """Cherche chaque identifiant dans HAL et écrit les documents trouvés dans `staging`.

    Un identifiant introuvable est inscrit dans `failed_lookups`. HAL indisponible laisse l'identifiant de côté, sans comptage : il reste dans la sélection du run suivant.

    `total` = identifiants à chercher, `new` = documents insérés, `extras["not_found"]` = identifiants introuvables.
    """
    metrics = PhaseMetrics(seen=len(ids))
    if not ids:
        nothing_to_do(log)
        return metrics

    async def _fetch(
        client: httpx2.AsyncClient, identifier: str
    ) -> LookupOutcome[Mapping[str, JsonValue]]:
        fetched = await fetch_one(client, identifier)
        await asyncio.sleep(HAL_DELAY)
        return fetched

    with track_progress(len(ids), f"{LAST_BRANCH}HAL", log, count_kept=True) as progress:

        def _write(
            conn: Connection, identifier: str, result: LookupOutcome[Mapping[str, JsonValue]]
        ) -> None:
            if isinstance(result, NotFound):
                record_failed_lookup(conn, "hal", id_type, identifier)
                metrics.add(not_found=1)
            elif not isinstance(result, Unavailable):
                if _stage(conn, result):
                    metrics.add(new=1)
                    progress.keep()
            progress.advance()

        await run_fetch_pool(
            ids,
            conn,
            max_concurrent=HAL_MAX_CONCURRENT,
            commit_every=_COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
        )
    return metrics


async def fetch_missing_hal_by_id(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans HAL les documents repérés par hal-id (OpenAlex, ScanR) et absents du staging. Un hal-id introuvable est cherché de nouveau après `retry_after_days` jours."""
    return await _fetch_ids(
        conn,
        log,
        get_missing_hal_ids(conn, retry_after_days=retry_after_days),
        fetch_one=lambda client, hal_id: search_one(
            client, f"halId_s:{hal_id}", label=f"halId {hal_id}"
        ),
        id_type="hal_id",
    )


async def fetch_missing_hal_by_nnt(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans HAL les thèses soutenues repérées par NNT (theses.fr) et sans document HAL. Un NNT introuvable est cherché de nouveau après `retry_after_days` jours."""
    return await _fetch_ids(
        conn,
        log,
        get_missing_nnts(conn, retry_after_days=retry_after_days),
        fetch_one=lambda client, nnt: search_one(client, f"nntId_s:{nnt}", label=f"NNT {nnt}"),
        id_type="nnt",
    )


class HalDoiSearch:
    """Recherche par DOI dans HAL (`DoiSearch`) : requête Solr `doiId_s`, un appel par DOI."""

    source_key = "hal"
    batch_size = 1
    # API Solr publique sans rate-limit documenté : 5 requêtes simultanées restent courtoises.
    max_concurrent = 5
    request_delay_s = 0.0

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        doi = dois[0]
        outcome = await search_one(client, f'doiId_s:"{doi}"', label=f"DOI {doi}")
        if isinstance(outcome, NotFound):
            return DoiBatchResult(not_found=[doi])
        if isinstance(outcome, Unavailable):
            return DoiBatchResult()
        return DoiBatchResult(records=[outcome])
