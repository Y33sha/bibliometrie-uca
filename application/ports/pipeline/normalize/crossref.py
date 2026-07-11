"""Port : SQL du normaliseur CrossRef.

Implémenté par `infrastructure.queries.pipeline.normalize.crossref.PgCrossrefNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class CrossrefNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur CrossRef."""

    def upsert_crossref_source_publication(
        self,
        conn: Connection,
        *,
        doi: str,
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
        cited_by_count: int | None,
        biblio: JsonValue,
        meta: JsonValue,
    ) -> int: ...
