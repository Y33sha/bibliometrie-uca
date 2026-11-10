"""Recherche dans OPS par numéro de brevet : phase `fetch_missing` (tâche `fetch_missing.ops_by_number`) et rafraîchissement d'une famille (`fetch_stale`).

Les numéros cherchés sont ceux des publications du périmètre sans famille OPS, absents de toute famille en base. Un numéro de publication donne directement sa famille, comme un numéro de demande autre qu'international. À défaut, un numéro de demande est cherché comme priorité (`pr`) : une priorité jamais publiée elle-même figure seulement dans les demandes qui la revendiquent. Une demande internationale, écrite sans son office de dépôt, est cherchée comme numéro quelconque (`num`). Une famille trouvée est gardée si ses numéros contiennent le numéro cherché.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping

import httpx2
from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifierRole, SourceIdentifierType
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from pipeline.http.lookup import NOT_FOUND, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.common.failed_lookups import (
    LookupIdType,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.common.lookup import LookupBatch, LookupChannel, look_up
from pipeline.ingestion.ops.api import (
    SEARCH_PATH,
    application_family_path,
    family_path,
    get_json_async,
    publication_forms,
    search_page,
    search_params,
)
from pipeline.ingestion.ops.family import family_key, family_members, family_numbers
from pipeline.ingestion.ops.harvest import family_document
from pipeline.runtime.observability.metrics import PhaseMetrics

SOURCE = "ops"

_PUBLICATION: LookupIdType = SourceIdentifierType.PATENT_PUBLICATION_NUMBER.value
_APPLICATION: LookupIdType = SourceIdentifierType.PATENT_APPLICATION_NUMBER.value


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
    """Renvoie les numéros de publication et de demande des publications du périmètre sans famille OPS, absents des familles en base, avec leurs types.

    Un numéro cherché en vain est cherché de nouveau après `retry_after_days` jours.
    """
    numbers: dict[str, set[LookupIdType]] = {}
    for row in conn.execute(_MISSING_NUMBERS_SQL, {"retry_after_days": retry_after_days}):
        numbers.setdefault(row.id_value, set()).add(row.id_type)
    return {number: frozenset(types) for number, types in numbers.items()}


async def _family(
    client: httpx2.AsyncClient, path: str, label: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie le document de la famille servie à `path`, son absence ou l'indisponibilité d'OPS."""
    body = await get_json_async(client, path, label=label)
    if isinstance(body, NotFound | Unavailable):
        return body
    key = family_key(family_members(body if isinstance(body, Mapping) else {}))
    return family_document(body, key) if key else NOT_FOUND


async def _family_by_search(
    client: httpx2.AsyncClient, number: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie la famille de la première publication trouvée par la recherche d'un numéro de demande : comme priorité (`pr`), ou, pour une demande internationale écrite sans son office de dépôt, comme numéro quelconque (`num`). Une recherche refusée pour surcharge donne `UNAVAILABLE` sans attente : le numéro attend le run suivant."""
    query = f"num={number}" if number.startswith("WO") else f"pr={number}"
    body = await get_json_async(
        client,
        SEARCH_PATH,
        search_params(query, 1),
        wait_on_overload=False,
        label=f"recherche {query}",
    )
    if isinstance(body, NotFound | Unavailable):
        return body
    _, hits = search_page(body)
    if not hits:
        return NOT_FOUND
    return await _family(client, family_path(hits[0].publication), f"famille {hits[0].publication}")


async def fetch_by_number(
    client: httpx2.AsyncClient, number: str, types: frozenset[LookupIdType]
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie la famille qui contient `number` sous l'un de ses types, son absence ou l'indisponibilité d'OPS."""
    lookups: list[Callable[[], Awaitable[LookupOutcome[Mapping[str, JsonValue]]]]] = []
    if _PUBLICATION in types:
        lookups += [
            lambda form=form: _family(client, family_path(form), f"famille {form}")
            for form in publication_forms(number)
        ]
    if _APPLICATION in types:
        if (path := application_family_path(number)) is not None:
            lookups.append(lambda: _family(client, path, f"famille de la demande {number}"))
        lookups.append(lambda: _family_by_search(client, number))
    for lookup in lookups:
        found = await lookup()
        if isinstance(found, Unavailable):
            return found
        if isinstance(found, NotFound):
            continue
        published, filed = family_numbers(
            family_members(found["family"] if isinstance(found["family"], Mapping) else {})
        )
        if (_PUBLICATION in types and number in published) or (
            _APPLICATION in types and number in filed
        ):
            return found
    return NOT_FOUND


async def fetch_by_source_id(
    client: httpx2.AsyncClient, source_id: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie la famille d'identifiant `source_id`, numéro de sa priorité la plus ancienne (`fetch_stale`)."""
    return await fetch_by_number(client, source_id, frozenset({_APPLICATION}))


async def fetch_missing_ops_by_number(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans OPS les familles des numéros des publications du périmètre sans famille, et les écrit dans `staging`.

    Un numéro introuvable est inscrit dans `failed_lookups`, sous chacun de ses types cherchés.
    """
    numbers = get_missing_numbers(conn, retry_after_days=retry_after_days)

    def record_absent(conn: Connection, number: str) -> None:
        for id_type in numbers[number]:
            record_failed_lookup(conn, SOURCE, id_type, number)

    async def fetch(client: httpx2.AsyncClient, batch: list[str]) -> LookupBatch | Unavailable:
        (number,) = batch
        found = await fetch_by_number(client, number, numbers[number])
        if isinstance(found, Unavailable):
            return found
        if isinstance(found, NotFound):
            return LookupBatch(absent=[number])
        return LookupBatch(records=[found])

    channel = LookupChannel(
        source=SOURCE,
        fetch=fetch,
        on_absent=record_absent,
        stage=lambda staging, family: staging.stage(
            SOURCE, family, entry_mode=StagingEntryMode.FETCH_MISSING_PATENT_NUMBER
        ),
    )
    return await look_up(conn, log, channel, list(numbers))
