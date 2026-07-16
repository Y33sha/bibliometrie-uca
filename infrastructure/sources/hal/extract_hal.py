"""Adapter HAL pour la phase extract : HTTP (Solr search API) + écritures staging + config.

Implémente le port `application.ports.pipeline.extract.hal.HalExtractAdapter`.
L'orchestration de la phase (requête unique sur l'union des collections,
pagination `cursorMark`, batch commits) vit côté
`application.pipeline.extract.extract_hal`.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.hal import HalExtractAdapter, HalExtractConfig
from domain.publications.identifiers import clean_doi
from infrastructure.sources.api_limits import HAL_DELAY, hal_per_page_for
from infrastructure.sources.common import upsert_staging
from infrastructure.sources.config import (
    get_api_base_urls,
    get_hal_collections,
    get_years,
)
from infrastructure.sources.hal.fields import HAL_FIELDS
from infrastructure.sources.http_retry import http_request_with_retry


def _build_url(base_url: str) -> str:
    """Construit l'URL de recherche HAL à partir de la base API."""
    return f"{base_url}/"


def extract_doi(doc: dict[str, Any]) -> str | None:
    """Extrait le DOI nettoyé d'un document HAL (champ `doiId_s`).

    `doiId_s` arrive en scalaire depuis l'extraction bulk Solr, mais en liste
    depuis l'API de recherche par hal-id (cross-import) : les deux formes sont
    gérées avant nettoyage.
    """
    doi = doc.get("doiId_s")
    if isinstance(doi, list):
        doi = doi[0] if doi else None
    return clean_doi(doi)


class PgHalExtractAdapter(HalExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `HalExtractAdapter`.

    Construit avec une `base_url` (URL Solr HAL). Les méthodes HTTP
    formatent les paramètres Solr et délèguent à `http_request_with_retry`.
    Les méthodes SQL écrivent dans `staging` via les statements préparés
    ci-dessus.
    """

    def __init__(self, base_url: str) -> None:
        self._url = _build_url(base_url)
        self._last_request_at: float | None = None

    def _get(self, params: dict[str, Any], label: str) -> dict[str, Any]:
        """GET Solr HAL, auto rate-limité : au moins `HAL_DELAY` entre deux appels.

        L'adapter se rate-limite seul, quel que soit l'appelant — l'orchestrateur
        n'ordonnance aucun `sleep`. On mesure l'écart depuis la dernière requête au
        lieu de dormir systématiquement après coup : le temps de traitement entre
        deux fetchs (parsing, upsert, commit) est déjà décompté du délai.
        """
        if self._last_request_at is not None:
            wait = HAL_DELAY - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        try:
            return http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)
        finally:
            self._last_request_at = time.monotonic()

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> HalExtractConfig:
        collections = get_hal_collections(conn)
        return HalExtractConfig(
            base_url=get_api_base_urls()["hal"],
            all_collections=dict(collections),
            n_collections=len(collections),
        )

    def get_years(self, conn: Connection, *, start_year: int | None = None) -> list[int]:
        return get_years(conn, start_year=start_year)

    # ── Parsing & requête (pur, sans I/O) ──────────────────────

    def build_query(self, years: list[int] | None, since: str | None = None) -> str:
        """Construit la requête Solr HAL (paramètre `q`).

        - `years` borne `producedDateY_i:[min TO max]` (année de publication).
        - `since` (format `YYYY-MM-DD`) borne `submittedDate_tdate:[since TO *]`
          (date de dépôt HAL).
        Les deux filtres se combinent en AND : indispensable en mode daily,
        où l'on ne veut que les dépôts HAL récents *qui concernent aussi*
        la fenêtre d'années courante — sinon un dépôt tardif d'une vieille
        publication passe le filtre et pollue la base.
        Au moins un des deux paramètres doit être fourni.
        """
        if not years and not since:
            raise ValueError("build_query requires either `since` or a non-empty `years` list")
        parts: list[str] = []
        if years:
            parts.append(f"producedDateY_i:[{min(years)} TO {max(years)}]")
        if since:
            parts.append(f"submittedDate_tdate:[{since}T00:00:00Z TO *]")
        return " AND ".join(parts)

    def per_page_for(self, collection_code: str | None) -> int:
        """Taille de page Solr à utiliser pour une collection (cf. `api_limits`)."""
        return hal_per_page_for(collection_code)

    def extract_id(self, doc: dict[str, Any]) -> str:
        """Extrait le halId depuis un document HAL (champ `halId_s`)."""
        return doc.get("halId_s", "")

    def extract_doi(self, doc: dict[str, Any]) -> str | None:
        """Extrait le DOI nettoyé depuis un document HAL (champ `doiId_s`)."""
        return extract_doi(doc)

    def build_collections_fq(self, collection_codes: list[str]) -> str:
        """Filtre Solr `collCode_s:("C1" OR "C2" …)` couvrant toutes les collections
        configurées en une requête. Les codes sont quotés : certains portent un tiret
        (ex. `CHU-CLERMONTFERRAND`) que Solr interpréterait sinon comme un opérateur."""
        terms = " OR ".join(f'"{code}"' for code in collection_codes)
        return f"collCode_s:({terms})"

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page_cursor(self, query: str, fq: str, cursor_mark: str) -> dict[str, Any]:
        """Une page Solr en pagination `cursorMark` (full payload `HAL_FIELDS`).

        `cursor_mark` vaut `"*"` au premier appel, puis le `nextCursorMark` renvoyé par
        la réponse précédente. La réponse porte `response.docs` et `nextCursorMark` ;
        l'appelant boucle jusqu'à ce que le marqueur se stabilise. `sort=docid asc`
        (clé unique) est requis par cursorMark."""
        params = {
            "q": query,
            "fq": fq,
            "fl": ",".join(HAL_FIELDS),
            "rows": self.per_page_for(None),
            "sort": "docid asc",
            "cursorMark": cursor_mark,
            "wt": "json",
        }
        return self._get(params, f"HAL cursor={cursor_mark[:16]}")

    # ── SQL ────────────────────────────────────────────────────

    def upsert_work(
        self,
        conn: Connection,
        hal_id: str,
        doi: str | None,
        raw_data: dict[str, Any],
    ) -> UpsertOutcome:
        """UPSERT staging via le helper canonique."""
        inserted, changed = upsert_staging(
            conn, source="hal", source_id=hal_id, doi=doi, raw_data=raw_data
        )
        return UpsertOutcome.of(inserted=inserted, changed=changed)
