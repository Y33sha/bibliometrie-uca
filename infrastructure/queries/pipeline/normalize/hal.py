"""Query service : SQL du normaliseur HAL.

Appelé par `application/pipeline/normalize/normalize_hal.py`. Regroupe
l'UPSERT sur `source_publications` et la lecture d'idempotence. L'écriture
des `source_authorships` passe par le writer batch partagé
(`PgAuthorshipsBatchQueries`), commun à toutes les sources.
"""

from datetime import date

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.hal import HalNormalizeQueries
from domain.publications.metadata import normalized_title
from domain.types import JsonValue


def upsert_hal_source_publication(
    conn: Connection,
    *,
    hal_id: str,
    doi: str | None,
    title: str,
    pub_year: int | None,
    doc_type: str | None,
    hal_collections: list[str] | None,
    publication_id: int | None,
    staging_id: int,
    external_ids: JsonValue,
    journal_id: int | None,
    oa_status: str | None,
    embargo_until: date | None,
    language: str | None,
    container_title: str | None,
    abstract: str | None,
    keywords: list[str] | None,
    topics: JsonValue,
    biblio: JsonValue,
    urls: list[str] | None,
) -> int:
    """UPSERT d'un document HAL dans `source_publications`."""
    # cf. note dans normalize_openalex : `external_ids` non-null en colonne,
    # on substitue None → {} avant binding.
    if external_ids is None:
        external_ids = {}
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, doi, title, title_normalized, pub_year, doc_type,
             hal_collections, publication_id, staging_id, external_ids,
             journal_id, oa_status, embargo_until, language, container_title,
             abstract, keywords, topics, biblio, urls)
        VALUES ('hal', :hal_id, :doi, :title, :title_normalized, :pub_year, :doc_type,
                :hal_collections, :publication_id, :staging_id, :external_ids,
                :journal_id, :oa_status, :embargo_until, :language, :container_title,
                :abstract, :keywords, :topics, :biblio, :urls)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doi = COALESCE(source_publications.doi, EXCLUDED.doi),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            hal_collections = (
                SELECT array_agg(DISTINCT c ORDER BY c)
                FROM unnest(
                    COALESCE(source_publications.hal_collections, '{}') ||
                    COALESCE(EXCLUDED.hal_collections, '{}')
                ) AS c
            ),
            external_ids = source_publications.external_ids || EXCLUDED.external_ids,
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            embargo_until = EXCLUDED.embargo_until,
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls),
            keys_dirty = true,
            updated_at = clock_timestamp()
        RETURNING id
    """).bindparams(
        bindparam("external_ids", type_=JSONB),
        bindparam("topics", type_=JSONB),
        bindparam("biblio", type_=JSONB),
    )
    row = conn.execute(
        stmt,
        {
            "hal_id": hal_id,
            "doi": doi,
            "title": title,
            "title_normalized": normalized_title(title),
            "pub_year": pub_year,
            "doc_type": doc_type,
            "hal_collections": hal_collections,
            "publication_id": publication_id,
            "staging_id": staging_id,
            "external_ids": external_ids,
            "journal_id": journal_id,
            "oa_status": oa_status,
            "embargo_until": embargo_until,
            "language": language,
            "container_title": container_title,
            "abstract": abstract,
            "keywords": keywords,
            "topics": topics,
            "biblio": biblio,
            "urls": urls,
        },
    ).one()
    return row.id


class PgHalNormalizeQueries(HalNormalizeQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.normalize.hal.HalNormalizeQueries`."""

    def upsert_hal_source_publication(
        self,
        conn: Connection,
        *,
        hal_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str | None,
        hal_collections: list[str] | None,
        publication_id: int | None,
        staging_id: int,
        external_ids: JsonValue,
        journal_id: int | None,
        oa_status: str | None,
        embargo_until: date | None,
        language: str | None,
        container_title: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        topics: JsonValue,
        biblio: JsonValue,
        urls: list[str] | None,
    ) -> int:
        return upsert_hal_source_publication(
            conn,
            hal_id=hal_id,
            doi=doi,
            title=title,
            pub_year=pub_year,
            doc_type=doc_type,
            hal_collections=hal_collections,
            publication_id=publication_id,
            staging_id=staging_id,
            external_ids=external_ids,
            journal_id=journal_id,
            oa_status=oa_status,
            embargo_until=embargo_until,
            language=language,
            container_title=container_title,
            abstract=abstract,
            keywords=keywords,
            topics=topics,
            biblio=biblio,
            urls=urls,
        )
