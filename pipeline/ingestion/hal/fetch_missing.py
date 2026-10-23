"""Recherches dans HAL de la phase `fetch_missing`.

- `fetch_missing_hal_by_id` (tâche `fetch_missing.hal_by_id`) : hal-ids portés par des documents OpenAlex et ScanR, absents du staging HAL ; requête Solr `halId_s`.
- `fetch_missing_hal_by_nnt` (tâche `fetch_missing.hal_by_nnt`) : NNT de thèses soutenues sans document HAL ; requête Solr `nntId_s`. Réservé au mode `full`.
- `HalDoiSearch` (tâche `fetch_missing.doi.hal`) : recherche par DOI, pilotée par `pipeline.ingestion.common.doi_search`.

Les deux premières passent par la boucle commune (`pipeline.ingestion.common.lookup`), sur `HAL_MAX_CONCURRENT` workers.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence

import httpx2
from sqlalchemy import Connection, text

from domain.source_records.external_ids import ExternalIdType
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.common.failed_lookups import (
    LookupIdType,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.common.lookup import LookupBatch, LookupChannel, look_up, one_at_a_time
from pipeline.ingestion.hal.api import search_one
from pipeline.runtime.observability.log_format import nothing_to_do
from pipeline.runtime.observability.metrics import PhaseMetrics

# Requêtes simultanées à HAL ; le débit suit le budget de la source (`api_params.MAX_PER_SECOND`).
HAL_MAX_CONCURRENT = 5

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
    """Cherche chaque identifiant dans HAL et écrit les documents trouvés dans `staging`. Un identifiant introuvable est inscrit dans `failed_lookups`.

    Compteurs de `look_up`, et `extras["not_found"]` = identifiants introuvables.
    """
    if not ids:
        nothing_to_do(log)
        return PhaseMetrics()
    return await look_up(
        conn,
        log,
        LookupChannel(
            source="hal",
            fetch=one_at_a_time(fetch_one),
            on_absent=lambda conn, identifier: record_failed_lookup(
                conn, "hal", id_type, identifier
            ),
            stage=lambda staging, doc: staging.stage(
                "hal", doc, entry_mode=StagingEntryMode.FETCH_MISSING_HAL
            ),
            max_concurrent=HAL_MAX_CONCURRENT,
        ),
        ids,
    )


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

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        doi = dois[0]
        outcome = await search_one(client, f'doiId_s:"{doi}"', label=f"DOI {doi}")
        if isinstance(outcome, NotFound):
            return LookupBatch(absent=[doi])
        if isinstance(outcome, Unavailable):
            return UNAVAILABLE
        return LookupBatch(records=[outcome])
