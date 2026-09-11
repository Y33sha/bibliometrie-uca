"""Adapter HAL pour `application.pipeline.fetch_missing.hal`.

Implémente les lookups SQL (hal-ids d'OpenAlex et de ScanR, NNT de theses.fr), les fetchs HTTP async (par halId et par NNT) et les inserts staging.

L'orchestration (boucles async, commits intermédiaires) vit côté `application.pipeline.fetch_missing.hal`.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection, text

from application.ports.pipeline.fetch_missing.hal import (
    HalFetchMissingAdapter,
    NntInsertResult,
)
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.pipeline.extract.staging import upsert_not_found_stub, upsert_staging
from infrastructure.sources.api_params import API_BASE_URLS, HAL_DELAY
from infrastructure.sources.hal.extract_hal import extract_doi
from infrastructure.sources.hal.fields import HAL_FIELDS_STR
from infrastructure.sources.http_retry import http_request_with_retry_async

# HAL ne publie pas de seuil officiel : on combine concurrence (5 workers)
# + délai par worker (HAL_DELAY = 0.5 s) → ~6-7 req/s sustained, sans burst.
HAL_MAX_CONCURRENT = 5

_MISSING_HAL_IDS_SQL = text(
    """
    SELECT DISTINCT h.hal_id
    FROM source_publications sp
    JOIN publications p ON p.id = sp.publication_id
    CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> 'hal_id') AS h(hal_id)
    WHERE sp.source IN ('openalex', 'scanr')
      AND p.in_perimeter
      AND jsonb_typeof(sp.external_ids -> 'hal_id') = 'array'
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'hal' AND s.source_id = h.hal_id
      )
    """
)

_MISSING_NNTS_SQL = text(
    """
    SELECT sp.external_ids ->> 'nnt' AS nnt
    FROM source_publications sp
    JOIN publications p ON p.id = sp.publication_id
    WHERE sp.source = 'theses'
      AND p.in_perimeter
      AND sp.external_ids ->> 'nnt' IS NOT NULL
      AND p.doc_type != 'ongoing_thesis'
      AND NOT EXISTS (
          SELECT 1 FROM source_publications hal
          WHERE hal.publication_id = p.id AND hal.source = 'hal'
      )
    """
)


def insert_staging_hal(
    conn: Connection, hal_id: str, doi: str | None, doc: Mapping[str, JsonValue]
) -> None:
    """Insère un document dans staging HAL.

    Si le document existe et a changé (hash différent), met à jour et remet `processed = FALSE`.
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
        self._base_url = API_BASE_URLS["hal"]

    # ── Lookups SQL ────────────────────────────────────────────

    def find_missing_hal_ids(self, conn: Connection) -> list[str]:
        """hal-ids que des `source_publications` OpenAlex ou ScanR portent dans `external_ids.hal_id`, absents du staging HAL.

        Seules comptent les publications in-périmètre : un document hors périmètre n'entraîne aucune recherche dans HAL. La sélection lit les `source_publications` du run précédent : les documents extraits pendant le run y entrent au run suivant.
        """
        return list(conn.execute(_MISSING_HAL_IDS_SQL).scalars())

    def find_missing_nnts(self, conn: Connection) -> list[str]:
        """NNT des `source_publications` theses.fr des publications in-périmètre, hors thèses en cours, dont la publication n'a aucune `source_publications` HAL."""
        return list(conn.execute(_MISSING_NNTS_SQL).scalars())

    # ── HTTP ───────────────────────────────────────────────────

    async def fetch_by_halid(
        self, client: httpx2.AsyncClient, hal_id: str
    ) -> Mapping[str, JsonValue] | None:
        return await self._search_one(client, f"halId_s:{hal_id}", label=f"halId {hal_id}")

    async def fetch_by_nnt(
        self, client: httpx2.AsyncClient, nnt: str
    ) -> Mapping[str, JsonValue] | None:
        return await self._search_one(client, f"nntId_s:{nnt}", label=f"NNT {nnt}")

    async def _search_one(
        self, client: httpx2.AsyncClient, query: str, *, label: str
    ) -> Mapping[str, JsonValue] | None:
        """Premier document de la recherche Solr `query`, ou `None` quand la réponse est vide. Une erreur réseau ou HTTP lève `httpx2.HTTPError`."""
        data = as_mapping(
            await http_request_with_retry_async(
                client,
                "GET",
                self._base_url,
                params={"q": query, "fl": HAL_FIELDS_STR, "wt": "json", "rows": "1"},
                timeout=15,
                label=label,
            )
        )
        docs = as_sequence(as_mapping(data.get("response")).get("docs"))
        return as_mapping(docs[0]) if docs else None

    # ── SQL (inserts) ──────────────────────────────────────────

    def insert_halid_result(
        self, conn: Connection, hal_id: str, doc: Mapping[str, JsonValue] | None
    ) -> bool:
        if doc:
            insert_staging_hal(conn, hal_id, extract_doi(doc), doc)
            return True
        upsert_not_found_stub(conn, source="hal", source_id=hal_id, entry_mode="cross_import_hal")
        return False

    def insert_nnt_result(
        self, conn: Connection, nnt: str, doc: Mapping[str, JsonValue] | None
    ) -> NntInsertResult:
        if not doc:
            return NntInsertResult(api_found=False, inserted=False)
        hal_id = as_str(doc.get("halId_s"))
        if not hal_id:
            return NntInsertResult(api_found=True, inserted=False)
        exists = conn.execute(
            text("SELECT 1 FROM staging WHERE source = 'hal' AND source_id = :id"),
            {"id": hal_id},
        ).first()
        if exists:
            return NntInsertResult(api_found=True, inserted=False)
        insert_staging_hal(conn, hal_id, extract_doi(doc), doc)
        return NntInsertResult(api_found=True, inserted=True)
