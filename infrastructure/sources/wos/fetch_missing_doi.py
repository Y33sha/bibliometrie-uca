"""Adapter WoS pour `application.pipeline.extract.fetch_missing_doi`.

WoS accepte une requête groupée par DOI (`DO=("doi1" OR "doi2" OR ...)`).
Lot de 20 DOI par requête pour éviter des URLs trop longues, pagination
interne de `WOS_PER_PAGE` records, retries exponentiels sur 429/erreurs.

Certains DOI (preprints Zenodo, arXiv, SSRN, Research Square...) sont
systématiquement absents de WoS : on les filtre côté client pour éviter
les appels inutiles.

Adapter async (`AsyncFetchMissingDoiAdapter`). Les requêtes DOI
individuelles (via batch de 20 et WOS_PER_PAGE=10) sont stables ;
les pages larges de l'API WoS le sont moins.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.sources.api_limits import WOS_DELAY, WOS_PER_PAGE
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import get_api_base_urls, get_wos_api_key
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.wos.parsing import clean_doi_for_wos, extract_doi, extract_ut

log = logging.getLogger(__name__)

_INSERT_WOS_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES ('wos', :source_id, :doi, :raw_data, :raw_hash)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
            THEN EXCLUDED.raw_data ELSE staging.raw_data END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
            THEN FALSE ELSE staging.processed END,
        last_seen_at = now()
    """
).bindparams(bindparam("raw_data", type_=JSONB))


class WosFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "wos"
    batch_size = 20
    # WoS API Clarivate : instable historiquement et rate-limit serré
    # (variable selon contrat, généralement 2-5 req/s). 2 workers + 500 ms
    # de pause par worker garantissent un débit ≈ 2 req/s peak (avec
    # latence WoS typique ~500 ms), sous le seuil habituel et sans burst
    # initial.
    max_concurrent = 2
    request_delay_s = 0.5

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls(conn).get("wos", "https://api.clarivate.com/api/wos")
        self.headers = {"X-ApiKey": get_wos_api_key(conn), "Accept": "application/json"}

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        clean = [d for d in (clean_doi_for_wos(x) for x in dois) if d]
        if not clean:
            return []
        query = "DO=(" + " OR ".join(f'"{d}"' for d in clean) + ")"

        records: list[dict] = []
        first_record = 1
        while True:
            params = {
                "databaseId": "WOS",
                "usrQuery": query,
                "count": WOS_PER_PAGE,
                "firstRecord": first_record,
            }
            try:
                data = await http_request_with_retry_async(
                    client,
                    "GET",
                    self.base_url,
                    headers=self.headers,
                    params=params,
                    timeout=60,
                    # Backoff initial 4s pour matcher le comportement sync historique
                    # (2^(attempt+2) = 4, 8, 16, 32, 64)
                    initial_backoff=4.0,
                    retry_on_empty_body=True,
                    label=f"rec {first_record}",
                )
            except httpx.HTTPStatusError as e:
                # WoS 400 = requête mal formée ou lot sans correspondance : skip silencieux
                if e.response.status_code == 400:
                    log.warning("WoS 400 rec %d, lot ignoré", first_record)
                    return records
                raise
            except httpx.RequestError:
                break

            if not data:
                break
            try:
                recs_container = data.get("Data", {}).get("Records", {})
                if not isinstance(recs_container, dict):
                    break
                recs = recs_container.get("records", {})
                if not isinstance(recs, dict):
                    break
                recs = recs.get("REC", [])
            except (AttributeError, TypeError):
                break
            if isinstance(recs, dict):
                recs = [recs]
            if not recs:
                break
            records.extend(recs)

            total = int(data.get("QueryResult", {}).get("RecordsFound", 0))
            if first_record + WOS_PER_PAGE - 1 >= total:
                break
            first_record += WOS_PER_PAGE
            await asyncio.sleep(WOS_DELAY)

        return records

    def insert(self, conn: Connection, record: dict) -> bool:
        result = conn.execute(
            _INSERT_WOS_SQL,
            {
                "source_id": extract_ut(record),
                "doi": extract_doi(record),
                "raw_data": record,
                "raw_hash": compute_hash(record),
            },
        )
        conn.commit()
        return result.rowcount > 0
