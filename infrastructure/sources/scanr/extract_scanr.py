"""Adapter ScanR pour la phase extract : HTTP (Elasticsearch
search_after) + écritures staging + config.

Implémente le port
`application.ports.pipeline.extract.scanr.ScanrExtractAdapter`.
L'orchestration de la phase (boucle par année, pagination
`search_after`, commits intermédiaires) vit côté
`application.pipeline.extract.extract_scanr`.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.extract.scanr import (
    ScanrExtractAdapter,
    ScanrExtractConfig,
)
from domain.publications.identifiers import clean_doi
from infrastructure.sources.api_limits import SCANR_DELAY, SCANR_PER_PAGE
from infrastructure.sources.common import upsert_staging
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_scanr_credentials,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry


class PgScanrExtractAdapter(ScanrExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `ScanrExtractAdapter`.

    Construit avec une `base_url` (endpoint `_search`) et des
    `credentials` (basic auth Elasticsearch).
    """

    def __init__(self, base_url: str, credentials: tuple[str, str]) -> None:
        self._url = base_url
        self._auth = credentials
        self._last_request_at: float | None = None

    def _search(self, query: dict[str, Any]) -> dict[str, Any]:
        """POST Elasticsearch, auto rate-limité : au moins `SCANR_DELAY` entre deux appels.

        L'adapter se rate-limite seul, quel que soit l'appelant — l'orchestrateur
        n'ordonnance aucun `sleep`. On mesure l'écart depuis la dernière requête au
        lieu de dormir systématiquement après coup : le temps de traitement entre
        deux pages (upserts, commits intermédiaires) est déjà décompté du délai.
        """
        if self._last_request_at is not None:
            wait = SCANR_DELAY - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        try:
            return http_request_with_retry(
                "POST",
                self._url,
                json_body=query,
                auth=self._auth,
                timeout=30,
                label="ScanR search",
            )
        finally:
            self._last_request_at = time.monotonic()

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ScanrExtractConfig:
        affiliation_ids = get_extraction_api_ids(conn, "scanr")
        return ScanrExtractConfig(
            base_url=self._url,
            affiliation_ids=affiliation_ids,
        )

    def get_years(self, conn: Connection, *, mode: str) -> list[int]:
        return get_years(conn, mode=mode)

    # ── Parsing & requête (pur, sans I/O) ──────────────────────

    def build_query(
        self,
        year: int,
        affiliation_ids: list[str],
        search_after: list[Any] | None = None,
        *,
        track_total: bool = False,
    ) -> dict[str, Any]:
        """Construit la requête Elasticsearch pour ScanR.

        `bool.must` filtre l'année (term exact), `bool.should` matche au
        moins une affiliation (clause OR via `minimum_should_match: 1`).
        Le tri par `id.keyword` ASC permet la pagination `search_after`.

        `track_total` ne demande le comptage exact du set (`track_total_hits`)
        que sur la première page : Elasticsearch recompte sinon l'intégralité
        des résultats à *chaque* page, alors que le total n'est consommé qu'une
        fois (log + dénominateur de progression). Les pages suivantes le coupent
        (`False`), ce qui évite un full-count par page sur des sets de ~15k docs.
        """
        query: dict[str, Any] = {
            "size": SCANR_PER_PAGE,
            "track_total_hits": track_total,
            "query": {
                "bool": {
                    "must": [{"term": {"year": year}}],
                    "should": [
                        {"term": {"affiliations.id.keyword": aid}} for aid in affiliation_ids
                    ],
                    "minimum_should_match": 1,
                }
            },
            "sort": [{"id.keyword": "asc"}],
        }
        if search_after:
            query["search_after"] = search_after
        return query

    def extract_id(self, doc: dict[str, Any]) -> str:
        """Extrait l'identifiant ScanR (champ `id` du document)."""
        return doc.get("id", "")

    def extract_doi(self, doc: dict[str, Any]) -> str | None:
        """Extrait le premier DOI nettoyé depuis `externalIds`."""
        for ext in doc.get("externalIds") or []:
            if ext.get("type") == "doi":
                return clean_doi(ext.get("id"))
        return None

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: dict[str, Any]) -> dict[str, Any]:
        """Exécute une requête Elasticsearch (avec retry/backoff)."""
        return self._search(query)

    # ── SQL ────────────────────────────────────────────────────

    def upsert_doc(self, conn: Connection, doc: dict[str, Any]) -> tuple[bool, bool, bool]:
        """UPSERT staging via le helper canonique, ventilé `(new, updated, unchanged)`.

        Exactement un `True` : `updated` = contenu réécrit (hash changé),
        `unchanged` = re-vu identique.
        """
        inserted, changed = upsert_staging(
            conn,
            source="scanr",
            source_id=self.extract_id(doc),
            doi=self.extract_doi(doc),
            raw_data=doc,
        )
        if inserted:
            return (True, False, False)
        return (False, changed, not changed)


def get_scanr_credentials_from_db(conn: Connection) -> tuple[str, str]:
    """Helper pour le composition root : lit les credentials Basic Auth."""
    username, password = get_scanr_credentials(conn)
    return (username, password)
