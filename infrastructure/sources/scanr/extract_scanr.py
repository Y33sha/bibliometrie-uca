"""Adapter ScanR pour la phase extract : HTTP (Elasticsearch
search_after) + écritures staging + config.

Implémente le port
`application.ports.pipeline.extract.scanr.ScanrExtractAdapter`.
L'orchestration de la phase (boucle par année, pagination
`search_after`, commits intermédiaires) vit côté
`application.pipeline.extract.extract_scanr`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.scanr import (
    ScanrExtractAdapter,
    ScanrExtractConfig,
)
from domain.sources.scanr_extract import extract_doi, extract_scanr_id
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_scanr_credentials,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry

_UPDATE_SCANR_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, doi = :doi, raw_hash = :raw_hash, last_seen_at = now()
    WHERE source = 'scanr' AND source_id = :source_id AND (raw_hash IS DISTINCT FROM :raw_hash)
    """
).bindparams(bindparam("raw_data", type_=JSONB))

_INSERT_SCANR_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES ('scanr', :source_id, :doi, :raw_data, :raw_hash)
    ON CONFLICT (source, source_id) DO NOTHING
    """
).bindparams(bindparam("raw_data", type_=JSONB))


class PgScanrExtractAdapter(ScanrExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `ScanrExtractAdapter`.

    Construit avec une `base_url` (endpoint `_search`) et des
    `credentials` (basic auth Elasticsearch).
    """

    def __init__(self, base_url: str, credentials: tuple[str, str]) -> None:
        self._url = base_url
        self._auth = credentials

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ScanrExtractConfig:
        affiliation_ids = get_extraction_api_ids(conn, "scanr")
        return ScanrExtractConfig(
            base_url=self._url,
            affiliation_ids=affiliation_ids,
        )

    def get_years(self, conn: Connection, *, mode: str) -> list[int]:
        return get_years(conn, mode=mode)

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: dict[str, Any]) -> dict[str, Any]:
        """Exécute une requête Elasticsearch (avec retry/backoff)."""
        return http_request_with_retry(
            "POST",
            self._url,
            json_body=query,
            auth=self._auth,
            timeout=30,
            label="ScanR search",
        )

    # ── SQL ────────────────────────────────────────────────────

    def upsert_doc(
        self, conn: Connection, doc: dict[str, Any], *, is_new: bool
    ) -> tuple[bool, bool]:
        """INSERT pour les nouveaux, UPDATE conditionnel (sur raw_hash) sinon.

        Retourne `(inserted, updated)`. Au plus un des deux est `True`.
        """
        scanr_id = extract_scanr_id(doc)
        doi = extract_doi(doc)
        raw_hash = compute_hash(doc)
        params = {
            "source_id": scanr_id,
            "doi": doi,
            "raw_data": doc,
            "raw_hash": raw_hash,
        }
        if is_new:
            result = conn.execute(_INSERT_SCANR_SQL, params)
            return (bool(result.rowcount), False)
        result = conn.execute(_UPDATE_SCANR_SQL, params)
        return (False, bool(result.rowcount))


def get_scanr_credentials_from_db(conn: Connection) -> tuple[str, str]:
    """Helper pour le composition root : lit les credentials Basic Auth."""
    username, password = get_scanr_credentials(conn)
    return (username, password)
