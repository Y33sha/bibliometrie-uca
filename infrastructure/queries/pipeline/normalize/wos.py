"""Query service : SQL du normaliseur Web of Science.

Appelé par `application/pipeline/normalize/normalize_wos.py`. Porte l'UPSERT de
`source_publications` ; l'écriture des authorships / adresses passe par le writer
batch partagé (`infrastructure.queries.pipeline.normalize.authorships`).
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.wos import WosNormalizeQueries
from domain.types import JsonValue


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
    # cf. note dans normalize_openalex : `external_ids` non-null en colonne,
    # on substitue None → {} avant binding.
    if external_ids is None:
        external_ids = {}
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
            external_ids = source_publications.external_ids || EXCLUDED.external_ids,
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
