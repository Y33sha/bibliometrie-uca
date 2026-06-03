"""Port : SQL du normaliseur Web of Science.

Implémenté par `infrastructure.queries.normalize_wos.PgWosNormalizeQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class WosNormalizeQueries(Protocol):
    """Opérations SQL du normaliseur WoS."""

    def upsert_wos_source_publication(
        self,
        conn: Connection,
        *,
        ut: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        publication_id: int | None,
        staging_id: int,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        abstract: str | None,
        cited_by_count: int | None,
        biblio: JsonValue,
        keywords: list[str] | None,
        topics: JsonValue,
        urls: list[str] | None,
        external_ids: JsonValue,
    ) -> int: ...
