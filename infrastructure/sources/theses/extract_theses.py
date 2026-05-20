"""Adapter theses.fr pour la phase extract : HTTP (recherche paginée
par `debut`/`nombre`) + écritures staging + config.

Implémente le port
`application.ports.pipeline.extract.theses.ThesesExtractAdapter`.
L'orchestration de la phase (boucle par PPN × statut, filtre année
post-fetch) vit côté `application.pipeline.extract.extract_theses`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.theses import (
    ThesesExtractAdapter,
    ThesesExtractConfig,
)
from domain.sources.theses_extract import extract_doi, extract_theses_id
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import get_extraction_api_ids
from infrastructure.sources.http_retry import http_request_with_retry

_UPDATE_THESES_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, doi = :doi, raw_hash = :raw_hash, last_seen_at = now(),
        processed = CASE
            WHEN raw_hash IS DISTINCT FROM :raw_hash THEN FALSE
            ELSE processed
        END
    WHERE source = 'theses' AND source_id = :source_id
      AND (raw_hash IS DISTINCT FROM :raw_hash)
    """
).bindparams(bindparam("raw_data", type_=JSONB))

_INSERT_THESES_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES ('theses', :source_id, :doi, :raw_data, :raw_hash)
    ON CONFLICT (source, source_id) DO NOTHING
    """
).bindparams(bindparam("raw_data", type_=JSONB))


class PgThesesExtractAdapter(ThesesExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `ThesesExtractAdapter`.

    Construit avec une `base_url` (endpoint `/api/v1/theses/recherche/`).
    """

    def __init__(self, base_url: str) -> None:
        self._url = base_url

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ThesesExtractConfig:
        ppns = get_extraction_api_ids(conn, "theses")
        return ThesesExtractConfig(base_url=self._url, ppns=ppns)

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: str, *, debut: int, nombre: int) -> dict[str, Any]:
        """Récupère une page de résultats depuis l'API theses.fr."""
        params = {
            "q": query,
            "debut": debut,
            "nombre": nombre,
        }
        return http_request_with_retry(
            "GET",
            self._url,
            params=params,
            timeout=30,
            label=f"theses debut={debut}",
        )

    # ── SQL ────────────────────────────────────────────────────

    def upsert_these(
        self, conn: Connection, these: dict[str, Any], *, is_new: bool
    ) -> tuple[bool, bool]:
        """INSERT pour les nouvelles, UPDATE conditionnel (sur raw_hash) sinon."""
        theses_id = extract_theses_id(these)
        doi = extract_doi(these)
        raw_hash = compute_hash(these)
        params = {
            "source_id": theses_id,
            "doi": doi,
            "raw_data": these,
            "raw_hash": raw_hash,
        }
        if is_new:
            result = conn.execute(_INSERT_THESES_SQL, params)
            return (bool(result.rowcount), False)
        result = conn.execute(_UPDATE_THESES_SQL, params)
        return (False, bool(result.rowcount))
