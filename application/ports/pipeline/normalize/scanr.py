"""Port : SQL du normaliseur ScanR.

Implémenté par `infrastructure.queries.pipeline.normalize.scanr.PgScanrNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class ScanrNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur ScanR."""

    def upsert_scanr_source_publication(
        self,
        conn: Connection,
        *,
        scanr_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        publication_id: int | None,
        staging_id: int,
        external_ids: JsonValue,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        topics: JsonValue,
        cited_by_count: int | None,
        urls: list[str] | None,
        biblio: JsonValue,
    ) -> int: ...
