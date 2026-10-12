"""Recherches dans HAL de la phase `fetch_missing`.

- `fetch_missing_hal_by_id` (nœud `fetch_missing.hal_by_id`) : hal-ids portés par des documents OpenAlex et ScanR, absents du staging HAL ; requête Solr `halId_s`.
- `fetch_missing_hal_by_nnt` (nœud `fetch_missing.hal_by_nnt`) : NNT de thèses soutenues sans document HAL ; requête Solr `nntId_s`. Réservé au mode `full`.
- `HalDoiSearch` (nœud `fetch_missing.doi.hal`) : recherche par DOI, pilotée par `pipeline.sources.fetch_missing`.

Les deux premières tournent sur un pool de `HAL_MAX_CONCURRENT` workers, avec des écritures séquentielles et un commit tous les `_COMMIT_EVERY` identifiants.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence

import httpx2
from sqlalchemy import Connection, text

from domain.source_publications.external_ids import ExternalIdType
from domain.types import JsonValue, as_mapping, as_sequence, at_path
from pipeline.fetch_pool import run_fetch_pool
from pipeline.libelles import DERNIERE_BRANCHE, rien_a_faire
from pipeline.metrics import PhaseMetrics
from pipeline.progression import progression
from pipeline.sources.api_params import API_BASE_URLS, HAL_DELAY
from pipeline.sources.failed_lookups import (
    LookupIdType,
    forget_failed_doi_lookups,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.sources.fetch_missing import DoiBatchResult
from pipeline.sources.hal.fields import HAL_FIELDS_STR, extract_doi, extract_id
from pipeline.sources.http_retry import lookup_json_async
from pipeline.sources.lookup import NOT_FOUND, LookupOutcome, NotFound, Unavailable
from pipeline.sources.staging import upsert_staging

# HAL ne publie pas de seuil officiel : 5 workers et une pause de HAL_DELAY par worker donnent ~6-7 req/s, sans rafale.
HAL_MAX_CONCURRENT = 5

_COMMIT_EVERY = 50

_HAL_ID_PENDING = pending_failed_lookup_sql(
    source_sql="'hal'", id_type="hal_id", value_sql="h.hal_id"
)

_MISSING_HAL_IDS_SQL = text(
    f"""
    SELECT DISTINCT h.hal_id
    FROM source_publications sp
    JOIN publications p ON p.id = sp.publication_id
    CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> '{ExternalIdType.HAL_ID}') AS h(hal_id)
    WHERE sp.source IN ('openalex', 'scanr')
      AND p.in_perimeter
      AND jsonb_typeof(sp.external_ids -> '{ExternalIdType.HAL_ID}') = 'array'
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'hal' AND s.source_id = h.hal_id
      )
      AND NOT {_HAL_ID_PENDING}
    """
)

_NNT_PENDING = pending_failed_lookup_sql(
    source_sql="'hal'", id_type="nnt", value_sql=f"sp.external_ids ->> '{ExternalIdType.NNT}'"
)

_MISSING_NNTS_SQL = text(
    f"""
    SELECT sp.external_ids ->> '{ExternalIdType.NNT}' AS nnt
    FROM source_publications sp
    JOIN publications p ON p.id = sp.publication_id
    WHERE sp.source = 'theses'
      AND p.in_perimeter
      AND sp.external_ids ->> '{ExternalIdType.NNT}' IS NOT NULL
      AND p.doc_type != 'ongoing_thesis'
      AND NOT EXISTS (
          SELECT 1 FROM source_publications hal
          WHERE hal.publication_id = p.id AND hal.source = 'hal'
      )
      AND NOT EXISTS (
          SELECT 1 FROM source_publications hal
          WHERE hal.source = 'hal' AND hal.external_ids ->> '{ExternalIdType.NNT}' = sp.external_ids ->> '{ExternalIdType.NNT}'
      )
      AND NOT {_NNT_PENDING}
    """
)


def get_missing_hal_ids(conn: Connection) -> list[str]:
    """hal-ids que des `source_publications` OpenAlex ou ScanR portent dans `external_ids.hal_id`, absents du staging HAL.

    Seules comptent les publications in-périmètre : un document hors périmètre n'entraîne aucune recherche dans HAL. La sélection lit les `source_publications` du run précédent : les documents extraits pendant le run y entrent au run suivant.

    Écarte les hal-ids déjà cherchés en vain : HAL est leur source native, l'échec est définitif.
    """
    return list(conn.execute(_MISSING_HAL_IDS_SQL).scalars())


def get_missing_nnts(conn: Connection) -> list[str]:
    """NNT des `source_publications` theses.fr des publications in-périmètre, hors thèses en cours, dont la publication n'a aucune `source_publications` HAL.

    Écarte les NNT qu'un document HAL porte déjà, et ceux dont la recherche a échoué et attend encore sa reprise.
    """
    return list(conn.execute(_MISSING_NNTS_SQL).scalars())


async def search_one(
    client: httpx2.AsyncClient, query: str, *, label: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Premier document de la recherche Solr `query`, ou `NOT_FOUND` quand la réponse est vide."""
    outcome = await lookup_json_async(
        client,
        "GET",
        API_BASE_URLS["hal"],
        params={"q": query, "fl": HAL_FIELDS_STR, "wt": "json", "rows": "1"},
        timeout=15,
        not_found_statuses=frozenset(),
        label=label,
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    docs = as_sequence(at_path(outcome, "response").get("docs"))
    return as_mapping(docs[0]) if docs else NOT_FOUND


def _stage(conn: Connection, doc: Mapping[str, JsonValue]) -> bool:
    """Écrit un document HAL dans `staging`. Rend `True` sur une insertion."""
    inserted, _ = upsert_staging(
        conn,
        source="hal",
        source_id=extract_id(doc),
        doi=extract_doi(doc),
        raw_data=doc,
        entry_mode="fetch_missing_hal",
    )
    return inserted


async def _fetch_ids(
    conn: Connection,
    log: logging.Logger,
    ids: Sequence[str],
    *,
    fetch_one: Callable[
        [httpx2.AsyncClient, str], Awaitable[LookupOutcome[Mapping[str, JsonValue]]]
    ],
    id_type: LookupIdType,
    retry_after_days: int,
) -> PhaseMetrics:
    """Cherche chaque identifiant dans HAL et écrit les documents trouvés dans `staging`.

    Un identifiant introuvable est inscrit dans `failed_lookups`. HAL indisponible laisse l'identifiant de côté, sans comptage : il reste dans la sélection du run suivant.

    `total` = identifiants à chercher, `new` = documents insérés, `extras["not_found"]` = identifiants introuvables.
    """
    metrics = PhaseMetrics(seen=len(ids))
    if not ids:
        rien_a_faire(log)
        return metrics

    async def _fetch(
        client: httpx2.AsyncClient, identifier: str
    ) -> LookupOutcome[Mapping[str, JsonValue]]:
        fetched = await fetch_one(client, identifier)
        await asyncio.sleep(HAL_DELAY)
        return fetched

    with progression(len(ids), f"{DERNIERE_BRANCHE}HAL", log, compte_retenus=True) as avancement:

        def _write(
            conn: Connection, identifier: str, result: LookupOutcome[Mapping[str, JsonValue]]
        ) -> None:
            if isinstance(result, NotFound):
                record_failed_lookup(
                    conn, "hal", id_type, identifier, retry_after_days=retry_after_days
                )
                metrics.add(not_found=1)
            elif not isinstance(result, Unavailable) and extract_id(result):
                if _stage(conn, result):
                    metrics.add(new=1)
                    avancement.retient()
            avancement.avance()

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
    """Cherche dans HAL les documents repérés par hal-id (OpenAlex, ScanR) et absents du staging."""
    return await _fetch_ids(
        conn,
        log,
        get_missing_hal_ids(conn),
        fetch_one=lambda client, hal_id: search_one(
            client, f"halId_s:{hal_id}", label=f"halId {hal_id}"
        ),
        id_type="hal_id",
        retry_after_days=retry_after_days,
    )


async def fetch_missing_hal_by_nnt(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans HAL les thèses soutenues repérées par NNT (theses.fr) et sans document HAL. Un NNT introuvable est cherché de nouveau après `retry_after_days` jours."""
    return await _fetch_ids(
        conn,
        log,
        get_missing_nnts(conn),
        fetch_one=lambda client, nnt: search_one(client, f"nntId_s:{nnt}", label=f"NNT {nnt}"),
        id_type="nnt",
        retry_after_days=retry_after_days,
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

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        if not extract_id(record):
            return False
        inserted, _ = upsert_staging(
            conn,
            source="hal",
            source_id=extract_id(record),
            doi=extract_doi(record),
            raw_data=record,
            entry_mode="fetch_missing_doi",
        )
        forget_failed_doi_lookups(conn, "hal", [extract_doi(record)])
        return inserted
