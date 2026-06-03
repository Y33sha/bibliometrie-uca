"""Query service : SQL du normaliseur OpenAlex.

Appelé par `application/pipeline/normalize/normalize_openalex.py`.
Regroupe les UPSERT sur `source_publications` et `source_authorships`,
ainsi que les lectures d'idempotence et les déduplications Zenodo.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.openalex import OpenalexNormalizeQueries
from domain.types import JsonValue


def upsert_openalex_source_publication(
    conn: Connection,
    *,
    openalex_id: str,
    doi: str | None,
    title: str,
    pub_year: int | None,
    doc_type: str | None,
    publication_id: int | None,
    staging_id: int,
    external_ids: JsonValue,
    urls: list[str] | None,
    cited_by_count: int | None,
    journal_id: int | None,
    oa_status: str | None,
    language: str | None,
    container_title: str | None,
    is_retracted: bool | None,
    biblio: JsonValue,
    abstract: str | None,
    keywords: list[str] | None,
    topics_json: JsonValue,
) -> int:
    """UPSERT d'un document OpenAlex dans `source_publications`."""
    # `external_ids` est garanti non-null en colonne (CHECK + NOT NULL) ;
    # côté Python on substitue None → {} avant binding pour éviter que
    # `bindparam(type_=JSONB)` ne produise JSONB null (≠ SQL NULL).
    if external_ids is None:
        external_ids = {}
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids, urls, cited_by_count,
             journal_id, oa_status, language, container_title,
             is_retracted, biblio, abstract, keywords, topics)
        VALUES ('openalex', :openalex_id, :doi, :title, :pub_year, :doc_type,
                :publication_id, :staging_id, :external_ids, :urls, :cited_by_count,
                :journal_id, :oa_status, :language, :container_title,
                :is_retracted, :biblio, :abstract, :keywords, :topics_json)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            external_ids = source_publications.external_ids || EXCLUDED.external_ids,
            urls = COALESCE(EXCLUDED.urls, source_publications.urls),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            is_retracted = COALESCE(EXCLUDED.is_retracted, source_publications.is_retracted),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            updated_at = clock_timestamp()
        RETURNING id
    """).bindparams(
        bindparam("external_ids", type_=JSONB),
        bindparam("biblio", type_=JSONB),
        bindparam("topics_json", type_=JSONB),
    )
    row = conn.execute(
        stmt,
        {
            "openalex_id": openalex_id,
            "doi": doi,
            "title": title,
            "pub_year": pub_year,
            "doc_type": doc_type,
            "publication_id": publication_id,
            "staging_id": staging_id,
            "external_ids": external_ids,
            "urls": urls,
            "cited_by_count": cited_by_count,
            "journal_id": journal_id,
            "oa_status": oa_status,
            "language": language,
            "container_title": container_title,
            "is_retracted": is_retracted,
            "biblio": biblio,
            "abstract": abstract,
            "keywords": keywords,
            "topics_json": topics_json,
        },
    ).one()
    return row.id


def staging_has_openalex_doi(conn: Connection, doi: str) -> bool:
    """Vrai si le DOI est déjà présent dans `staging` pour `source='openalex'`."""
    return (
        conn.execute(
            text("SELECT id FROM staging WHERE source = 'openalex' AND lower(doi) = lower(:doi)"),
            {"doi": doi},
        ).first()
        is not None
    )


def count_openalex_table(conn: Connection, table: str) -> int:
    """Compte les lignes d'une table avec `source = 'openalex'` (liste blanche)."""
    if table not in ("source_publications", "source_authorships"):
        raise ValueError(f"Table inattendue : {table!r}")
    return conn.execute(
        text(f"SELECT COUNT(*) AS cnt FROM {table} WHERE source = 'openalex'")
    ).scalar_one()


class PgOpenalexNormalizeQueries(OpenalexNormalizeQueries):
    """Adapter PostgreSQL pour `application.ports.normalize_openalex.OpenalexNormalizeQueries`."""

    def upsert_openalex_source_publication(
        self,
        conn: Connection,
        *,
        openalex_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        publication_id: int | None,
        staging_id: int,
        external_ids: JsonValue,
        urls: list[str] | None,
        cited_by_count: int | None,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        is_retracted: bool | None,
        biblio: JsonValue,
        abstract: str | None,
        keywords: list[str] | None,
        topics_json: JsonValue,
    ) -> int:
        return upsert_openalex_source_publication(
            conn,
            openalex_id=openalex_id,
            doi=doi,
            title=title,
            pub_year=pub_year,
            doc_type=doc_type,
            publication_id=publication_id,
            staging_id=staging_id,
            external_ids=external_ids,
            urls=urls,
            cited_by_count=cited_by_count,
            journal_id=journal_id,
            oa_status=oa_status,
            language=language,
            container_title=container_title,
            is_retracted=is_retracted,
            biblio=biblio,
            abstract=abstract,
            keywords=keywords,
            topics_json=topics_json,
        )

    def staging_has_openalex_doi(self, conn: Connection, doi: str) -> bool:
        return staging_has_openalex_doi(conn, doi)

    def count_openalex_table(self, conn: Connection, table: str) -> int:
        return count_openalex_table(conn, table)
