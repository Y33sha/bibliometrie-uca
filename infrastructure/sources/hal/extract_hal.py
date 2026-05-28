"""Adapter HAL pour la phase extract : HTTP (Solr search API) + écritures staging + config.

Implémente le port `application.ports.pipeline.extract.hal.HalExtractAdapter`.
L'orchestration de la phase (boucle par collection, aiguillage
full/incremental, batch commits) vit côté
`application.pipeline.extract.extract_hal`.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.hal import HalExtractAdapter, HalExtractConfig
from domain.publications.identifiers import clean_doi
from infrastructure.sources.api_limits import HAL_DELAY, hal_per_page_for
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import (
    get_api_base_urls,
    get_hal_collections,
    get_hal_extra_collections,
    get_years,
)
from infrastructure.sources.hal.fields import HAL_FIELDS
from infrastructure.sources.http_retry import http_request_with_retry

# Max imposé par HAL pour `rows` sur une requête Solr (n'utilisé que pour
# la passe préview IDs-only, payload minuscule).
_HAL_PREVIEW_ROWS = 10000


_TAG_COLLECTION_SQL = text(
    """
    UPDATE staging
    SET hal_collections = CASE
            WHEN hal_collections IS NULL THEN ARRAY[:code]::TEXT[]
            WHEN :code = ANY(hal_collections) THEN hal_collections
            ELSE hal_collections || CAST(:code AS TEXT)
        END,
        last_seen_at = now()
    WHERE source = 'hal' AND source_id = ANY(:ids)
    """
)

_UPSERT_HAL_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, raw_hash)
    VALUES ('hal', :hal_id, :doi, :raw_data, ARRAY[:collection], :raw_hash)
    ON CONFLICT (source, source_id) DO UPDATE SET
        hal_collections = CASE
            WHEN staging.hal_collections IS NULL THEN ARRAY[EXCLUDED.hal_collections[1]]
            WHEN EXCLUDED.hal_collections[1] = ANY(staging.hal_collections)
                THEN staging.hal_collections
            ELSE staging.hal_collections || EXCLUDED.hal_collections[1]
        END,
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data
            ELSE staging.raw_data
        END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE
            ELSE staging.processed
        END,
        last_seen_at = now()
    """
).bindparams(bindparam("raw_data", type_=JSONB))


def _build_url(base_url: str) -> str:
    """Construit l'URL de recherche HAL à partir de la base API."""
    return f"{base_url}/"


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
        extra_collections = get_hal_extra_collections(conn)
        all_collections = dict(collections)
        for code in extra_collections:
            if code not in all_collections:
                all_collections[code] = code
        return HalExtractConfig(
            base_url=get_api_base_urls(conn).get("hal", "https://api.archives-ouvertes.fr/search/"),
            all_collections=all_collections,
            n_collections=len(collections),
            n_extra=len(extra_collections),
        )

    def get_years(self, conn: Connection, *, mode: str) -> list[int]:
        return get_years(conn, mode=mode)

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
        return clean_doi(doc.get("doiId_s"))

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: str, collection_code: str, start: int) -> dict[str, Any]:
        """Récupère une page de résultats (full payload avec HAL_FIELDS)."""
        params = {
            "q": query,
            "fl": ",".join(HAL_FIELDS),
            "rows": self.per_page_for(collection_code),
            "start": start,
            "sort": "docid asc",
            "wt": "json",
        }
        if collection_code:
            params["fq"] = f"collCode_s:{collection_code}"
        label = f"HAL coll={collection_code or '-'} start={start}"
        return self._get(params, label)

    def fetch_collection_ids(self, query: str, collection_code: str) -> list[str]:
        """Liste les halIds d'une collection via Solr `fl=halId_s` (payload minuscule)."""
        all_ids: list[str] = []
        start = 0
        total_count: int | None = None
        while True:
            params = {
                "q": query,
                "fl": "halId_s",
                "rows": _HAL_PREVIEW_ROWS,
                "start": start,
                "sort": "docid asc",
                "wt": "json",
                "fq": f"collCode_s:{collection_code}",
            }
            label = f"HAL preview coll={collection_code} start={start}"
            data = self._get(params, label)
            resp = data.get("response", {})
            if total_count is None:
                total_count = int(resp.get("numFound", 0))
            docs = resp.get("docs", [])
            all_ids.extend(d["halId_s"] for d in docs if d.get("halId_s"))
            start += len(docs)
            if start >= total_count or not docs:
                break
        return all_ids

    def fetch_single_work(self, hal_id: str) -> dict[str, Any] | None:
        """Récupère un document par halId, full HAL_FIELDS. Un appel = un document."""
        params = {
            "q": f'halId_s:"{hal_id}"',
            "fl": ",".join(HAL_FIELDS),
            "rows": 1,
            "wt": "json",
        }
        label = f"HAL single halId={hal_id}"
        data = self._get(params, label)
        docs = data.get("response", {}).get("docs", [])
        return docs[0] if docs else None

    # ── SQL ────────────────────────────────────────────────────

    def upsert_work(
        self,
        conn: Connection,
        hal_id: str,
        doi: str | None,
        raw_data: dict[str, Any],
        collection: str,
    ) -> None:
        """UPSERT staging : ajoute la collection, met à jour raw_data si hash changé."""
        conn.execute(
            _UPSERT_HAL_SQL,
            {
                "hal_id": hal_id,
                "doi": doi,
                "raw_data": raw_data,
                "collection": collection,
                "raw_hash": compute_hash(raw_data),
            },
        )

    def tag_existing_with_collection(
        self, conn: Connection, hal_ids: list[str], collection_code: str
    ) -> int:
        """Append `collection_code` à `hal_collections` pour les halIds donnés."""
        if not hal_ids:
            return 0
        result = conn.execute(_TAG_COLLECTION_SQL, {"code": collection_code, "ids": hal_ids})
        conn.commit()
        return result.rowcount
