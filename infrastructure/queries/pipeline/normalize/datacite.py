"""Query service : SQL du normaliseur DataCite.

Appelé par `application/pipeline/normalize/normalize_datacite.py`.
UPSERT sur `source_publications` (source='datacite').

Particularité DataCite, comme CrossRef : pas d'identifiant stable côté auteur
(les ORCID éventuels vivent sur l'identité de la signature,
`author_identifying_keys.person_identifiers`). La déduplication vers les
`persons` canoniques est faite plus tard par le pipeline `personnes`
(source-agnostique).
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.datacite import DataciteNormalizeQueries
from domain.publications.metadata import normalized_title
from domain.types import JsonValue


def upsert_datacite_source_publication(
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
) -> int:
    """UPSERT d'une publication DataCite dans `source_publications`. Retourne l'id."""
    if external_ids is None:
        external_ids = {}
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, doi, title, title_normalized, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, cited_by_count, biblio, meta)
        VALUES ('datacite', :source_id, :doi, :title, :title_normalized, :pub_year, :doc_type,
                :publication_id, :staging_id, :external_ids,
                :journal_id, :oa_status, :language, :container_title,
                :abstract, :keywords, :cited_by_count, :biblio, :meta)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doi = COALESCE(source_publications.doi, EXCLUDED.doi),
            external_ids = source_publications.external_ids || EXCLUDED.external_ids,
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            meta = COALESCE(EXCLUDED.meta, source_publications.meta),
            keys_dirty = true,
            updated_at = clock_timestamp()
        RETURNING id
    """).bindparams(
        bindparam("external_ids", type_=JSONB),
        bindparam("biblio", type_=JSONB),
        bindparam("meta", type_=JSONB),
    )
    row = conn.execute(
        stmt,
        {
            "source_id": doi,
            "doi": doi,
            "title": title,
            "title_normalized": normalized_title(title),
            "pub_year": pub_year,
            "doc_type": doc_type,
            "publication_id": publication_id,
            "staging_id": staging_id,
            "external_ids": external_ids,
            "journal_id": journal_id,
            "oa_status": oa_status,
            "language": language,
            "container_title": container_title,
            "abstract": abstract,
            "keywords": keywords,
            "cited_by_count": cited_by_count,
            "biblio": biblio,
            "meta": meta,
        },
    ).one()
    return row.id


class PgDataciteNormalizeQueries(DataciteNormalizeQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.normalize.datacite.DataciteNormalizeQueries`."""

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
    ) -> int:
        return upsert_datacite_source_publication(
            conn,
            doi=doi,
            title=title,
            pub_year=pub_year,
            doc_type=doc_type,
            publication_id=publication_id,
            staging_id=staging_id,
            external_ids=external_ids,
            journal_id=journal_id,
            oa_status=oa_status,
            language=language,
            container_title=container_title,
            abstract=abstract,
            keywords=keywords,
            cited_by_count=cited_by_count,
            biblio=biblio,
            meta=meta,
        )
