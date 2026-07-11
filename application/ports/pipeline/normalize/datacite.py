"""Port : SQL du normaliseur DataCite.

Implémenté par `infrastructure.queries.pipeline.normalize.datacite.PgDataciteNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class DataciteNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur DataCite."""

    def upsert_datacite_source_publication(
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
