"""Adapter OpenAlex pour `application.pipeline.extract.fetch_missing_doi`.

Un appel par DOI sur le filtre `doi:...` de l'API Works.

Chemin async (`run_async`). La boucle embarrassingly parallel des
DOIs manquants exploite le polite pool OpenAlex (10 req/s) via un
sémaphore.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from infrastructure.sources.common import compute_hash, record_doi_not_found
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth
from infrastructure.sources.openalex.parsing import extract_doi, extract_openalex_id

_INSERT_OA_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES ('openalex', :source_id, :doi, :raw_data, :raw_hash, FALSE)
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


class OpenalexFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "openalex"
    batch_size = 1
    # OpenAlex impose 10 req/s comme plafond documenté, quel que soit le pool
    # (polite via `mailto` ou authentifié via `api_key`). `auth_params()` envoie
    # `api_key` si configurée (cas prod), sinon `mailto`.
    # Calibrage : 3 workers + 100 ms de pause par worker après chaque fetch.
    # Avec une latence OpenAlex typique ~280 ms, débit effectif
    # ≈ 3 / (0.28 + 0.1) ≈ 7.9 req/s. Marge de sécurité sous le seuil de 10
    # req/s pour absorber les bursts initiaux et la variabilité de latence.
    max_concurrent = 3
    request_delay_s = 0.1

    base_url: str

    def configure(self, conn: Connection) -> None:
        init_auth(api_key=get_openalex_api_key(conn), email=get_polite_pool_email(conn))
        self.base_url = get_api_base_urls()["openalex"]

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        doi = dois[0]
        params = {
            "filter": f"doi:{doi}",
            "select": SELECT_FIELDS,
            **auth_params(),
        }
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self.base_url,
                params=params,
                timeout=30,
                label=f"DOI {doi}",
            )
        except httpx.RequestError:
            return []
        results = data.get("results", [])
        if not results:
            # Réponse OpenAlex valide, zéro résultat : DOI confirmé absent.
            return [not_found_marker(doi)]
        return results[:1]

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "openalex", record["_doi"])
            conn.commit()
            return False

        result = conn.execute(
            _INSERT_OA_SQL,
            {
                "source_id": extract_openalex_id(record),
                "doi": extract_doi(record),
                "raw_data": record,
                "raw_hash": compute_hash(record),
            },
        )
        conn.commit()
        return result.rowcount > 0
