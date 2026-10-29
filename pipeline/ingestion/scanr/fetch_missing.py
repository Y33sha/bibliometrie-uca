"""Recherches dans ScanR de la phase `fetch_missing`.

- `ScanrDoiSearch` (tâche `fetch_missing.doi.scanr`) : recherche par DOI, pilotée par `pipeline.ingestion.common.doi_search`.
- `fetch_missing_scanr_by_hal_id` (tâche `fetch_missing.scanr_by_hal_id`) : hal-id des documents HAL et OpenAlex, absents de ScanR.

Une requête Elasticsearch `terms` sur `externalIds.id.keyword` cherche un lot de 50 identifiants, en authentification basique.

ScanR stocke les DOI en casse variable : les DOI de ses réponses passent par `clean_doi` avant d'être comparés aux DOI demandés.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx2
from sqlalchemy import Connection, text

from domain.publications.identifiers import clean_doi
from domain.source_records.identifiers import SourceIdentifierType
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.common.failed_lookups import pending_failed_lookup_sql, record_failed_lookup
from pipeline.ingestion.common.lookup import LookupBatch, LookupChannel, look_up
from pipeline.ingestion.scanr.api import search
from pipeline.runtime.observability.metrics import PhaseMetrics

BATCH_SIZE = 50
# L'API Elasticsearch publique est sans plafond documenté : 5 requêtes simultanées restent courtoises.
MAX_CONCURRENT = 5


async def search_by_external_ids(
    client: httpx2.AsyncClient,
    ids: list[str],
    *,
    id_type: str,
    normalize: Callable[[str | None], str | None] = lambda value: value,
) -> LookupBatch | Unavailable:
    """Documents ScanR dont les `externalIds` contiennent l'un des identifiants, de ce type.

    Un identifiant sans document est confirmé absent. `normalize` ramène les identifiants de la réponse à la forme des identifiants demandés.
    """
    query: dict[str, JsonValue] = {
        # Un identifiant peut désigner plusieurs documents ScanR.
        "size": 2 * len(ids),
        "query": {"terms": {"externalIds.id.keyword": ids}},
    }
    records = await search(client, query, label=f"lot de {len(ids)} {id_type}")
    if isinstance(records, NotFound | Unavailable):
        return UNAVAILABLE
    found = {
        normalize(as_str(fields.get("id")))
        for rec in records
        for ext in as_sequence(rec.get("externalIds"))
        if as_str((fields := as_mapping(ext)).get("type")) == id_type
    }
    return LookupBatch(records=records, absent=[i for i in ids if i not in found])


class ScanrDoiSearch:
    """Recherche par DOI dans ScanR (`DoiSearch`), par lots (`search_by_external_ids`)."""

    source_key = "scanr"
    batch_size = BATCH_SIZE
    max_concurrent = MAX_CONCURRENT

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        # Comparaison sur DOI nettoyé, cohérente avec les DOI en minuscules de `get_missing_dois`.
        return await search_by_external_ids(client, dois, id_type="doi", normalize=clean_doi)


_HAL_ID_PENDING = pending_failed_lookup_sql(
    source_sql="'scanr'", id_type="hal_id", value_sql="c.hal_id"
)

_MISSING_HAL_IDS_SQL = text(
    f"""
    WITH candidates AS (
        SELECT sr.source_id AS hal_id
        FROM source_records sr
        JOIN publications p ON p.id = sr.publication_id
        WHERE sr.source = 'hal' AND p.in_perimeter
        UNION
        SELECT h.id_value
        FROM source_records sr
        JOIN publications p ON p.id = sr.publication_id
        JOIN source_record_identifiers h
          ON h.source_record_id = sr.id AND h.id_type = '{SourceIdentifierType.HAL_ID}'
             AND h.removed_by IS NULL
        WHERE sr.source = 'openalex' AND p.in_perimeter
    ),
    in_scanr AS (
        SELECT DISTINCT h.id_value AS hal_id
        FROM source_records sr
        JOIN source_record_identifiers h
          ON h.source_record_id = sr.id AND h.id_type = '{SourceIdentifierType.HAL_ID}'
             AND h.removed_by IS NULL
        WHERE sr.source = 'scanr'
    )
    SELECT c.hal_id
    FROM candidates c
    WHERE NOT EXISTS (SELECT 1 FROM in_scanr s WHERE s.hal_id = c.hal_id)
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'scanr' AND s.source_id = 'hal' || c.hal_id
      )
      AND NOT {_HAL_ID_PENDING}
    ORDER BY 1
    """
)


def get_missing_hal_ids(conn: Connection, *, retry_after_days: int) -> list[str]:
    """hal-id des documents HAL et OpenAlex des publications du périmètre, absents de ScanR.

    Un hal-id est présent dans ScanR quand un enregistrement source ScanR le contient, ou quand le staging ScanR a le document `hal<hal-id>`. Un hal-id cherché en vain l'est de nouveau après `retry_after_days` jours.
    """
    return list(
        conn.execute(_MISSING_HAL_IDS_SQL, {"retry_after_days": retry_after_days}).scalars()
    )


async def fetch_missing_scanr_by_hal_id(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans ScanR les documents repérés par hal-id (HAL, OpenAlex) et les écrit dans `staging`.

    Un hal-id introuvable est inscrit dans `failed_lookups`. Rend les compteurs de `look_up`, avec le nombre de hal-id introuvables (`not_found`).
    """
    return await look_up(
        conn,
        log,
        LookupChannel(
            source="scanr",
            fetch=lambda client, hal_ids: search_by_external_ids(client, hal_ids, id_type="hal"),
            on_absent=lambda conn, hal_id: record_failed_lookup(conn, "scanr", "hal_id", hal_id),
            stage=lambda staging, doc: staging.stage(
                "scanr", doc, entry_mode=StagingEntryMode.FETCH_MISSING_HAL_ID
            ),
            batch_size=BATCH_SIZE,
            max_concurrent=MAX_CONCURRENT,
        ),
        get_missing_hal_ids(conn, retry_after_days=retry_after_days),
    )
