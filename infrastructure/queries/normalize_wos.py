"""Query service : SQL du normaliseur Web of Science.

Appelé par `application/pipeline/normalize/normalize_wos.py`. Regroupe les
UPSERT batch (via SA executemany) sur `source_authorships` et
`source_authorship_addresses`, et les lectures/préchargements de caches.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.wos import (
    WosAddressBatchItem,
    WosAuthorshipAddressItem,
    WosAuthorshipBatchItem,
    WosNormalizeQueries,
)
from domain.json_types import JsonValue
from infrastructure.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


def upsert_wos_source_publication(
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
) -> int:
    """UPSERT d'un document WoS dans `source_publications`."""
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id,
             journal_id, oa_status, language, container_title,
             abstract, cited_by_count, biblio, keywords, topics,
             urls, external_ids)
        VALUES ('wos', :ut, :doi, :title, :pub_year, :doc_type,
                :publication_id, :staging_id,
                :journal_id, :oa_status, :language, :container_title,
                :abstract, :cited_by_count, :biblio, :keywords, :topics,
                :urls, :external_ids)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            updated_at = clock_timestamp()
        RETURNING id
    """).bindparams(
        bindparam("biblio", type_=JSONB),
        bindparam("topics", type_=JSONB),
        bindparam("external_ids", type_=JSONB),
    )
    row = conn.execute(
        stmt,
        {
            "ut": ut,
            "doi": doi,
            "title": title,
            "pub_year": pub_year,
            "doc_type": doc_type,
            "publication_id": publication_id,
            "staging_id": staging_id,
            "journal_id": journal_id,
            "oa_status": oa_status,
            "language": language,
            "container_title": container_title,
            "abstract": abstract,
            "cited_by_count": cited_by_count,
            "biblio": biblio,
            "keywords": keywords,
            "topics": topics,
            "urls": urls,
            "external_ids": external_ids,
        },
    ).one()
    return row.id


def upsert_addresses_batch(conn: Connection, values: list[WosAddressBatchItem]) -> None:
    """INSERT INTO addresses ON CONFLICT DO NOTHING pour un batch ``[{raw, norm}, ...]``."""
    if not values:
        return
    conn.execute(
        text("""
            INSERT INTO addresses (raw_text, normalized_text)
            VALUES (:raw, :norm)
            ON CONFLICT (md5(raw_text)) DO NOTHING
        """),
        values,
    )


def fetch_address_ids_by_raw_text(conn: Connection, raw_texts: list[str]) -> dict[str, int]:
    """Retourne `{raw_text: id}` pour un lot d'adresses."""
    rows = conn.execute(
        text("SELECT raw_text, id FROM addresses WHERE raw_text = ANY(:raw_texts)"),
        {"raw_texts": raw_texts},
    ).all()
    return {r.raw_text: r.id for r in rows}


def upsert_wos_source_authorships_batch(
    conn: Connection, values: list[WosAuthorshipBatchItem]
) -> None:
    """Batch UPSERT de `source_authorships` WoS.

    Les identifiants normalisés (`orcid`, `researcher_id`) vivent sur
    `person_identifiers` (entités auteurs WoS algorithmiques via
    `daisng_id` non fiables).
    """
    if not values:
        return
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, author_position,
             is_corresponding, author_name_normalized,
             source_structures, roles, raw_author_name, person_identifiers)
        VALUES ('wos', :spid, :author_position,
                :is_corresponding, :author_name_normalized,
                :source_structures, :roles, :raw_author_name, :person_identifiers)
        ON CONFLICT (source_publication_id, author_position) DO UPDATE SET
            is_corresponding = EXCLUDED.is_corresponding OR source_authorships.is_corresponding,
            author_name_normalized = COALESCE(
                EXCLUDED.author_name_normalized,
                source_authorships.author_name_normalized
            ),
            source_structures = COALESCE(
                EXCLUDED.source_structures,
                source_authorships.source_structures
            ),
            roles = EXCLUDED.roles,
            raw_author_name = EXCLUDED.raw_author_name,
            person_identifiers = EXCLUDED.person_identifiers
    """).bindparams(
        bindparam("person_identifiers", type_=JSONB),
    )
    conn.execute(stmt, values)


def fetch_source_authorship_ids_by_position(
    conn: Connection, *, source_publication_id: int, positions: list[int]
) -> dict[int, int]:
    """Retourne `{author_position: source_authorship_id}` pour un document WoS."""
    rows = conn.execute(
        text("""
            SELECT author_position, id FROM source_authorships
            WHERE source = 'wos'
              AND source_publication_id = :spid
              AND author_position = ANY(:positions)
        """),
        {"spid": source_publication_id, "positions": positions},
    ).all()
    return {r.author_position: r.id for r in rows}


def insert_source_authorship_addresses_batch(
    conn: Connection, values: list[WosAuthorshipAddressItem]
) -> None:
    """Batch INSERT de liens `source_authorship_addresses`. Dicts ``{sa_id, addr_id}``."""
    if not values:
        return
    conn.execute(
        text("""
            INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
            VALUES (:sa_id, :addr_id)
            ON CONFLICT (source_authorship_id, address_id) DO NOTHING
        """),
        values,
    )


class PgWosNormalizeQueries(WosNormalizeQueries):
    """Adapter PostgreSQL pour `application.ports.normalize_wos.WosNormalizeQueries`."""

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
    ) -> int:
        return upsert_wos_source_publication(
            conn,
            ut=ut,
            doi=doi,
            title=title,
            pub_year=pub_year,
            doc_type=doc_type,
            publication_id=publication_id,
            staging_id=staging_id,
            journal_id=journal_id,
            oa_status=oa_status,
            language=language,
            container_title=container_title,
            abstract=abstract,
            cited_by_count=cited_by_count,
            biblio=biblio,
            keywords=keywords,
            topics=topics,
            urls=urls,
            external_ids=external_ids,
        )

    def upsert_addresses_batch(self, conn: Connection, values: list[WosAddressBatchItem]) -> None:
        upsert_addresses_batch(conn, values)

    def fetch_address_ids_by_raw_text(
        self, conn: Connection, raw_texts: list[str]
    ) -> dict[str, int]:
        return fetch_address_ids_by_raw_text(conn, raw_texts)

    def upsert_wos_source_authorships_batch(
        self, conn: Connection, values: list[WosAuthorshipBatchItem]
    ) -> None:
        upsert_wos_source_authorships_batch(conn, values)

    def fetch_source_authorship_ids_by_position(
        self, conn: Connection, *, source_publication_id: int, positions: list[int]
    ) -> dict[int, int]:
        return fetch_source_authorship_ids_by_position(
            conn,
            source_publication_id=source_publication_id,
            positions=positions,
        )

    def insert_source_authorship_addresses_batch(
        self, conn: Connection, values: list[WosAuthorshipAddressItem]
    ) -> None:
        insert_source_authorship_addresses_batch(conn, values)

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)
