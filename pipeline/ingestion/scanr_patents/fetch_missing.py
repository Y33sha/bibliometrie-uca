"""Recherche dans ScanR brevets de la phase `fetch_missing` (tâche `fetch_missing.scanr_patents_by_number`).

Les numéros de brevet cherchés sont ceux des publications du périmètre sans famille ScanR brevets, absents de toute famille en base. Une requête Elasticsearch cherche un lot de numéros d'un même type : terme exact pour un numéro de demande, préfixe pour un numéro de publication, suivi dans ScanR de son code de type (`3053353A1`). Une famille renvoyée est gardée si ses numéros, lus comme à la normalisation, contiennent un numéro cherché.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifierRole, SourceIdentifierType
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.http.lookup import Unavailable
from pipeline.ingestion.common.failed_lookups import (
    LookupIdType,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.common.lookup import LookupBatch, LookupChannel, look_up
from pipeline.ingestion.scanr.api import ScanrIndex, search
from pipeline.ingestion.scanr_patents.harvest import EXCLUDED_FIELDS
from pipeline.ingestion.scanr_patents.normalize import family_identifiers
from pipeline.runtime.observability.metrics import PhaseMetrics

SOURCE = "scanr_patents"
BATCH_SIZE = 50
_HITS_PER_NUMBER = 5
"""Familles renvoyées au plus par numéro cherché : un préfixe de numéro de publication désigne parfois plusieurs familles."""

_NUMBER_TYPES: tuple[LookupIdType, ...] = (
    SourceIdentifierType.PATENT_PUBLICATION_NUMBER.value,
    SourceIdentifierType.PATENT_APPLICATION_NUMBER.value,
)


def _missing_numbers_sql(id_type: LookupIdType) -> str:
    return f"""
        SELECT DISTINCT i.id_value
        FROM source_records sr
        JOIN publications p ON p.id = sr.publication_id AND p.in_perimeter
        JOIN source_record_identifiers i
          ON i.source_record_id = sr.id AND i.id_type = '{id_type}'
             AND i.removed_by IS NULL AND i.role <> '{SourceIdentifierRole.RELATED}'
        WHERE sr.source <> '{SOURCE}'
          AND NOT EXISTS (
              SELECT 1 FROM source_records f
              WHERE f.publication_id = sr.publication_id AND f.source = '{SOURCE}'
          )
          AND NOT EXISTS (
              SELECT 1 FROM source_record_identifiers o
              JOIN source_records f ON f.id = o.source_record_id AND f.source = '{SOURCE}'
              WHERE o.id_type = i.id_type AND o.id_value = i.id_value
          )
          AND NOT {pending_failed_lookup_sql(source_sql=f"'{SOURCE}'", id_type=id_type, value_sql="i.id_value")}
        ORDER BY 1
    """  # noqa: S608 — types et source venus du code


def get_missing_numbers(
    conn: Connection, id_type: LookupIdType, *, retry_after_days: int
) -> list[str]:
    """Renvoie les numéros de type `id_type` des publications du périmètre sans famille ScanR brevets, absents des familles en base.

    Un numéro cherché en vain est cherché de nouveau après `retry_after_days` jours.
    """
    return list(
        conn.execute(
            text(_missing_numbers_sql(id_type)), {"retry_after_days": retry_after_days}
        ).scalars()
    )


def number_query(id_type: LookupIdType, numbers: list[str]) -> dict[str, JsonValue]:
    """Construit la requête Elasticsearch des familles d'un lot de numéros. ScanR écrit l'office à part du numéro."""
    digits = [n[2:] for n in numbers]
    if id_type == SourceIdentifierType.PATENT_APPLICATION_NUMBER:
        clause: JsonValue = {"terms": {"patents.applicationNumber.keyword": digits}}
    else:
        clause = {
            "bool": {
                "should": [{"prefix": {"patents.publicationNumber.keyword": d}} for d in digits]
            }
        }
    return {
        "size": _HITS_PER_NUMBER * len(numbers),
        "_source": {"excludes": list(EXCLUDED_FIELDS)},
        "query": {"bool": {"filter": [clause]}},
    }


def matching_families(
    id_type: LookupIdType, numbers: list[str], families: list[Mapping[str, JsonValue]]
) -> LookupBatch:
    """Renvoie les familles qui ont l'un des numéros cherchés, et les numéros absents de toutes."""
    wanted = set(numbers)
    kept: list[Mapping[str, JsonValue]] = []
    found: set[str] = set()
    for family in families:
        own = {i.value for i in family_identifiers(family) if i.id_type == id_type} & wanted
        if own:
            kept.append(family)
            found |= own
    return LookupBatch(records=kept, absent=[n for n in numbers if n not in found])


async def search_numbers(
    client: httpx2.AsyncClient, id_type: LookupIdType, numbers: list[str]
) -> LookupBatch | Unavailable:
    """Cherche dans ScanR brevets les familles d'un lot de numéros de type `id_type`."""
    families = await search(
        client,
        number_query(id_type, numbers),
        index=ScanrIndex.PATENTS,
        label=f"lot de {len(numbers)} {id_type}",
    )
    if isinstance(families, Unavailable):
        return families
    return matching_families(id_type, numbers, families)


def _channel(id_type: LookupIdType) -> LookupChannel:
    return LookupChannel(
        source=SOURCE,
        fetch=lambda client, numbers: search_numbers(client, id_type, numbers),
        on_absent=lambda conn, number: record_failed_lookup(conn, SOURCE, id_type, number),
        stage=lambda staging, family: staging.stage(
            SOURCE, family, entry_mode=StagingEntryMode.FETCH_MISSING_PATENT_NUMBER
        ),
        batch_size=BATCH_SIZE,
    )


async def fetch_missing_scanr_patents_by_number(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans ScanR brevets les familles des numéros de publication, puis de demande, des publications du périmètre sans famille, et les écrit dans `staging`.

    Un numéro introuvable est inscrit dans `failed_lookups`. Une famille trouvée par ses deux types de numéros est écrite deux fois, inchangée la seconde.
    """
    metrics = PhaseMetrics()
    for id_type in _NUMBER_TYPES:
        numbers = get_missing_numbers(conn, id_type, retry_after_days=retry_after_days)
        metrics.merge(await look_up(conn, log, _channel(id_type), numbers))
    return metrics
