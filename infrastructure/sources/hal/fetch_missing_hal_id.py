"""Adapter HAL pour `application.pipeline.extract.fetch_missing_hal_id`.

Implémente les lookups SQL (depuis OpenAlex, ScanR, NNT theses),
les fetchs HTTP async (par halId et par NNT) et les inserts staging.

L'orchestration (combinaison des refs, dedup, boucles async, commits
intermédiaires) vit côté
`application.pipeline.extract.fetch_missing_hal_id`.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import Connection, text

from application.ports.pipeline.extract.fetch_missing_hal_id import (
    HalFetchMissingAdapter,
    HalIdRef,
    NntRef,
)
from domain.publications.identifiers import extract_hal_id_from_url
from infrastructure.sources.api_limits import HAL_DELAY
from infrastructure.sources.common import upsert_not_found_stub, upsert_staging
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.hal.extract_hal import extract_doi
from infrastructure.sources.hal.fields import HAL_FIELDS_STR
from infrastructure.sources.http_retry_async import http_request_with_retry_async

# HAL ne publie pas de seuil officiel : on combine concurrence (5 workers)
# + délai par worker (HAL_DELAY = 0.5 s) → ~6-7 req/s sustained (5× le débit
# de la variante sync précédente), sans burst.
HAL_MAX_CONCURRENT = 5


def find_hal_ids_from_openalex(conn: Connection) -> list[dict[str, Any]]:
    """halIds référencés par OpenAlex mais absents de staging HAL.

    Deux sources, **toutes locations** (pas seulement la primary) :
    - staging non normalisé (raw_data.locations : landing_page_url + location.id OAI-PMH) — nouveaux docs du run en cours
    - source_publications déjà normalisés (external_ids.hal_id, liste) — docs des runs précédents

    Retourne `[{openalex_id, hal_id, landing_url}, ...]`.

    Conservé comme fonction libre (et non méthode) parce que l'extraction
    `landing_page_url → hal_id` passe par `extract_hal_id_from_url` (regex
    Python), faite après le SELECT. Le filtre `NOT EXISTS staging_hal`
    est appliqué en post-traitement sur l'ensemble dédupliqué.
    """
    results: dict[str, dict[str, Any]] = {}

    rows = conn.execute(
        text(
            """
            SELECT s.source_id AS openalex_id,
                   loc->>'landing_page_url' AS url,
                   loc->>'id' AS loc_id
            FROM staging s
            CROSS JOIN LATERAL jsonb_array_elements(s.raw_data->'locations') AS loc
            WHERE s.source = 'openalex'
              AND s.processed = FALSE
              AND jsonb_typeof(s.raw_data->'locations') = 'array'
            """
        )
    ).all()
    for row in rows:
        # hal_id depuis la landing page OU le location.id (OAI-PMH) — toutes locations.
        hal_id = extract_hal_id_from_url(row.url) or extract_hal_id_from_url(row.loc_id)
        if hal_id:
            results[hal_id] = {
                "openalex_id": row.openalex_id,
                "hal_id": hal_id,
                "landing_url": row.url,
            }

    rows = conn.execute(
        text(
            """
            SELECT source_id AS openalex_id, h AS hal_id
            FROM source_publications
            CROSS JOIN LATERAL jsonb_array_elements_text(external_ids->'hal_id') AS h
            WHERE source = 'openalex'
              AND jsonb_typeof(external_ids->'hal_id') = 'array'
            """
        )
    ).all()
    for row in rows:
        if row.hal_id not in results:
            results[row.hal_id] = {
                "openalex_id": row.openalex_id,
                "hal_id": row.hal_id,
                "landing_url": None,
            }

    if not results:
        return []
    already_staged = set(
        conn.execute(
            text("SELECT source_id FROM staging WHERE source = 'hal' AND source_id = ANY(:ids)"),
            {"ids": list(results.keys())},
        ).scalars()
    )
    return [r for hal_id, r in results.items() if hal_id not in already_staged]


def find_hal_ids_from_scanr(conn: Connection) -> list[dict[str, Any]]:
    """halIds référencés par ScanR mais absents de staging HAL.

    Deux sources :
    - source_publications ScanR déjà normalisés (external_ids.hal_id, liste)
    - staging ScanR non encore normalisé (raw_data.externalIds type='hal')

    Retourne `[{source: "scanr", hal_id, scanr_id}, ...]`.

    Conservé comme fonction libre pour permettre des tests d'intégration
    ciblés (cf. `tests/integration/infrastructure/sources/hal/test_fetch_missing_hal_id.py`).
    """
    rows = conn.execute(
        text(
            """
            SELECT sd.source_id AS scanr_id, h AS hal_id
            FROM source_publications sd
            CROSS JOIN LATERAL jsonb_array_elements_text(sd.external_ids->'hal_id') AS h
            WHERE sd.source = 'scanr'
              AND jsonb_typeof(sd.external_ids->'hal_id') = 'array'
              AND NOT EXISTS (
                  SELECT 1 FROM staging sh WHERE sh.source = 'hal' AND sh.source_id = h
              )
            """
        )
    ).all()
    results: dict[str, dict[str, Any]] = {
        row.hal_id: {"source": "scanr", "hal_id": row.hal_id, "scanr_id": row.scanr_id}
        for row in rows
    }

    rows = conn.execute(
        text(
            """
            SELECT s.source_id AS scanr_id, ext->>'id' AS hal_id
            FROM staging s,
                 jsonb_array_elements(s.raw_data->'externalIds') ext
            WHERE s.source = 'scanr'
              AND s.raw_data ? 'externalIds'
              AND ext->>'type' = 'hal'
              AND ext->>'id' IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM staging sh
                  WHERE sh.source = 'hal' AND sh.source_id = ext->>'id'
              )
            """
        )
    ).all()
    for row in rows:
        if row.hal_id not in results:
            results[row.hal_id] = {
                "source": "scanr",
                "hal_id": row.hal_id,
                "scanr_id": row.scanr_id,
            }

    return list(results.values())


def find_nnt_without_hal(conn: Connection) -> list[dict[str, Any]]:
    """NNT (thèses soutenues) sans document HAL associé.

    Recherche via `source_publications.external_ids->>'nnt'` pour les
    publications qui n'ont pas `'hal'` dans leurs sources et ne sont pas
    de type `ongoing_thesis`.

    Retourne `[{source: "nnt", nnt, theses_id}, ...]`.
    """
    rows = conn.execute(
        text(
            """
            SELECT sd.external_ids->>'nnt' AS nnt, sd.source_id AS theses_id
            FROM source_publications sd
            JOIN publications p ON p.id = sd.publication_id
            WHERE sd.source = 'theses'
              AND sd.external_ids->>'nnt' IS NOT NULL
              AND p.doc_type != 'ongoing_thesis'
              AND NOT EXISTS (
                  SELECT 1 FROM source_publications sd2
                  WHERE sd2.publication_id = p.id AND sd2.source = 'hal'
              )
            """
        )
    ).all()
    return [{"source": "nnt", "nnt": row.nnt, "theses_id": row.theses_id} for row in rows]


def insert_staging_hal(conn: Connection, hal_id: str, doi: str | None, doc: dict[str, Any]) -> None:
    """Insère un document dans staging HAL.

    Si le document existe et a changé (hash différent), met à jour et
    remet `processed = FALSE`.
    """
    upsert_staging(
        conn,
        source="hal",
        source_id=hal_id,
        doi=doi,
        raw_data=doc,
        entry_mode="cross_import_hal",
    )


class PgHalFetchMissingAdapter(HalFetchMissingAdapter):
    """Adapter PostgreSQL + HTTP pour `HalFetchMissingAdapter`."""

    max_concurrent: int = HAL_MAX_CONCURRENT
    delay_s: float = HAL_DELAY

    def __init__(self) -> None:
        self._base_url: str = ""

    def configure(self, conn: Connection) -> None:
        self._base_url = get_api_base_urls()["hal"]

    # ── Lookups SQL ────────────────────────────────────────────

    def find_halid_refs_from_openalex(self, conn: Connection) -> list[HalIdRef]:
        return [
            HalIdRef(
                source="openalex",
                hal_id=r["hal_id"],
                foreign_id=r["openalex_id"],
                landing_url=r.get("landing_url"),
            )
            for r in find_hal_ids_from_openalex(conn)
        ]

    def find_halid_refs_from_scanr(self, conn: Connection) -> list[HalIdRef]:
        return [
            HalIdRef(source="scanr", hal_id=r["hal_id"], foreign_id=r["scanr_id"])
            for r in find_hal_ids_from_scanr(conn)
        ]

    def find_nnt_refs_from_theses(self, conn: Connection) -> list[NntRef]:
        return [NntRef(nnt=r["nnt"], theses_id=r["theses_id"]) for r in find_nnt_without_hal(conn)]

    # ── HTTP ───────────────────────────────────────────────────

    async def fetch_by_halid(self, client: httpx.AsyncClient, hal_id: str) -> dict[str, Any] | None:
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self._base_url,
                params={
                    "q": f"halId_s:{hal_id}",
                    "fl": HAL_FIELDS_STR,
                    "wt": "json",
                    "rows": "1",
                },
                timeout=15,
                label=f"halId {hal_id}",
            )
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None
        docs = data.get("response", {}).get("docs", [])
        return docs[0] if docs else None

    async def fetch_by_nnt(self, client: httpx.AsyncClient, nnt: str) -> dict[str, Any] | None:
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                self._base_url,
                params={
                    "q": f"nntId_s:{nnt}",
                    "fl": HAL_FIELDS_STR,
                    "wt": "json",
                    "rows": "1",
                },
                timeout=15,
                label=f"NNT {nnt}",
            )
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None
        docs = data.get("response", {}).get("docs", [])
        return docs[0] if docs else None

    # ── SQL (inserts) ──────────────────────────────────────────

    def insert_halid_result(
        self, conn: Connection, hal_id: str, doc: dict[str, Any] | None
    ) -> bool:
        if doc:
            insert_staging_hal(conn, hal_id, extract_doi(doc), doc)
            return True
        upsert_not_found_stub(
            conn, source="hal", source_id=hal_id, entry_mode="cross_import_hal", rearm=True
        )
        return False

    def insert_nnt_result(
        self, conn: Connection, nnt: str, doc: dict[str, Any] | None
    ) -> tuple[bool, bool]:
        if not doc:
            return (False, False)
        hal_id = doc.get("halId_s")
        if not hal_id:
            return (True, False)
        exists = conn.execute(
            text("SELECT 1 FROM staging WHERE source = 'hal' AND source_id = :id"),
            {"id": hal_id},
        ).first()
        if exists:
            return (True, False)
        insert_staging_hal(conn, hal_id, extract_doi(doc), doc)
        return (True, True)
