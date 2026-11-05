"""Recherche dans ScanR brevets de la phase `fetch_missing` (tâche `fetch_missing.scanr_patents_by_number`).

Les numéros de brevet cherchés sont ceux des publications du périmètre sans famille ScanR brevets, absents de toute famille en base. Une requête Elasticsearch cherche un lot de numéros des deux types : terme exact pour un numéro de demande, préfixe pour un numéro de publication, suivi dans ScanR de son code de type (`3053353A1`). Une famille renvoyée est gardée si ses numéros, lus comme à la normalisation, contiennent un numéro cherché sous son type.
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

_PUBLICATION: LookupIdType = SourceIdentifierType.PATENT_PUBLICATION_NUMBER.value
_APPLICATION: LookupIdType = SourceIdentifierType.PATENT_APPLICATION_NUMBER.value

type NumberTypes = Mapping[str, frozenset[LookupIdType]]
"""Types sous lesquels chaque numéro est cherché. Un même numéro WO peut être cherché comme publication et comme demande."""


def _missing_numbers_sql(id_type: LookupIdType) -> str:
    return f"""
        SELECT DISTINCT i.id_type::text AS id_type, i.id_value
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
    """  # noqa: S608 — types et source venus du code


_MISSING_NUMBERS_SQL = text(
    f"{_missing_numbers_sql(_PUBLICATION)} UNION {_missing_numbers_sql(_APPLICATION)} ORDER BY 2, 1"
)


def get_missing_numbers(
    conn: Connection, *, retry_after_days: int
) -> dict[str, frozenset[LookupIdType]]:
    """Renvoie les numéros de publication et de demande des publications du périmètre sans famille ScanR brevets, absents des familles en base, avec leurs types.

    Un numéro cherché en vain est cherché de nouveau après `retry_after_days` jours.
    """
    numbers: dict[str, set[LookupIdType]] = {}
    for row in conn.execute(_MISSING_NUMBERS_SQL, {"retry_after_days": retry_after_days}):
        numbers.setdefault(row.id_value, set()).add(row.id_type)
    return {number: frozenset(types) for number, types in numbers.items()}


def number_query(numbers: NumberTypes) -> dict[str, JsonValue]:
    """Construit la requête Elasticsearch des familles d'un lot de numéros. ScanR écrit l'office à part du numéro."""
    filed = [n[2:] for n, types in numbers.items() if _APPLICATION in types]
    published = [n[2:] for n, types in numbers.items() if _PUBLICATION in types]
    clauses: list[JsonValue] = [
        {"prefix": {"patents.publicationNumber.keyword": d}} for d in published
    ]
    if filed:
        clauses.append({"terms": {"patents.applicationNumber.keyword": filed}})
    return {
        "size": _HITS_PER_NUMBER * len(numbers),
        "_source": {"excludes": list(EXCLUDED_FIELDS)},
        "query": {"bool": {"filter": [{"bool": {"should": clauses}}]}},
    }


def matching_families(numbers: NumberTypes, families: list[Mapping[str, JsonValue]]) -> LookupBatch:
    """Renvoie les familles qui ont l'un des numéros cherchés sous son type, et les numéros absents de toutes."""
    wanted = {(id_type, number) for number, types in numbers.items() for id_type in types}
    kept: list[Mapping[str, JsonValue]] = []
    found: set[str] = set()
    for family in families:
        own = {(i.id_type.value, i.value) for i in family_identifiers(family)} & wanted
        if own:
            kept.append(family)
            found |= {number for _, number in own}
    return LookupBatch(records=kept, absent=[n for n in numbers if n not in found])


async def search_numbers(
    client: httpx2.AsyncClient, numbers: NumberTypes
) -> LookupBatch | Unavailable:
    """Cherche dans ScanR brevets les familles d'un lot de numéros."""
    families = await search(
        client,
        number_query(numbers),
        index=ScanrIndex.PATENTS,
        label=f"lot de {len(numbers)} numéros de brevet",
    )
    if isinstance(families, Unavailable):
        return families
    return matching_families(numbers, families)


async def fetch_missing_scanr_patents_by_number(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans ScanR brevets les familles des numéros des publications du périmètre sans famille, et les écrit dans `staging`.

    Un numéro introuvable est inscrit dans `failed_lookups`, sous chacun de ses types cherchés.
    """
    numbers = get_missing_numbers(conn, retry_after_days=retry_after_days)

    def record_absent(conn: Connection, number: str) -> None:
        for id_type in numbers[number]:
            record_failed_lookup(conn, SOURCE, id_type, number)

    channel = LookupChannel(
        source=SOURCE,
        fetch=lambda client, batch: search_numbers(client, {n: numbers[n] for n in batch}),
        on_absent=record_absent,
        stage=lambda staging, family: staging.stage(
            SOURCE, family, entry_mode=StagingEntryMode.FETCH_MISSING_PATENT_NUMBER
        ),
        batch_size=BATCH_SIZE,
    )
    return await look_up(conn, log, channel, list(numbers))
