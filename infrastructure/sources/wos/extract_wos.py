"""Adapter WoS pour la phase extract : HTTP (API Expanded) +
écritures staging + config.

Implémente le port `application.ports.pipeline.extract.wos.WosExtractAdapter`.
L'orchestration de la phase (boucle par année, pauses, breather) vit
côté `application.pipeline.extract.extract_wos`.
"""

from __future__ import annotations

from typing import Any

import requests
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract._common import BatchInsertCounts
from application.ports.pipeline.extract.wos import WosExtractAdapter, WosExtractConfig
from domain.sources.wos_extract import build_query, extract_doi, extract_ut
from infrastructure.sources.api_limits import WOS_PER_PAGE
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry

_INSERT_WOS_BATCH_SQL = text(
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
    RETURNING (xmax = 0) AS inserted
    """
).bindparams(bindparam("raw_data", type_=JSONB))


class PgWosExtractAdapter(WosExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `WosExtractAdapter`.

    Construit avec une `base_url` et une `api_key`. Les méthodes HTTP
    formatent les paramètres et délèguent à `http_request_with_retry`
    avec un backoff conservateur (`initial_backoff=2.0`) — WoS est plus
    sensible aux 429.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._url = base_url
        self._headers = {"X-ApiKey": api_key, "Accept": "application/json"}

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> WosExtractConfig:
        affiliations = get_extraction_api_ids(conn, "wos")
        return WosExtractConfig(
            base_url=self._url,
            affiliations=affiliations,
        )

    def get_years(self, conn: Connection, *, mode: str) -> list[int]:
        return get_years(conn, mode=mode)

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, year: int, first_record: int, affiliations: list[str]) -> dict[str, Any]:
        """Récupère une page de résultats via une recherche complète.

        Note : la pagination via queryId ne fonctionne pas de façon fiable
        (réponses vides), on refait une recherche avec firstRecord à chaque page.
        """
        params = {
            "databaseId": "WOS",
            "usrQuery": build_query(year, affiliations),
            "count": WOS_PER_PAGE,
            "firstRecord": first_record,
        }
        return http_request_with_retry(
            "GET",
            self._url,
            params=params,
            headers=self._headers,
            timeout=60,
            retry_on_empty_body=True,
            initial_backoff=2.0,
            label=f"({year}, rec {first_record})",
        )

    def check_quota(self) -> str | None:
        """Probe l'API pour récupérer le header `X-REC-AmtPerYear-Remaining`."""
        resp = requests.get(
            self._url,
            headers=self._headers,
            params={
                "databaseId": "WOS",
                "usrQuery": "OG=(test)",
                "count": "0",
                "firstRecord": "1",
            },
            timeout=30,
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Erreur d'authentification WoS ({resp.status_code}). "
                f"Vérifier la clé API. Réponse : {resp.text[:300]}"
            )
        if resp.status_code != 200:
            return None
        return resp.headers.get("X-REC-AmtPerYear-Remaining")

    # ── SQL ────────────────────────────────────────────────────

    def insert_batch(self, conn: Connection, records: list[dict[str, Any]]) -> BatchInsertCounts:
        """UPSERT bulk d'un batch de records WoS, ventilé new/updated via `xmax`.

        Le caller est responsable du `conn.commit()` après cette méthode.
        """
        if not records:
            return BatchInsertCounts(new=0, updated=0)
        batch = [
            {
                "source_id": extract_ut(rec),
                "doi": extract_doi(rec),
                "raw_data": rec,
                "raw_hash": compute_hash(rec),
            }
            for rec in records
        ]
        result = conn.execute(_INSERT_WOS_BATCH_SQL, batch)
        rows = result.all()
        new_count = sum(1 for r in rows if r.inserted)
        return BatchInsertCounts(new=new_count, updated=len(rows) - new_count)
