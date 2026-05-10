"""Query service : SQL du normaliseur ScanR.

Appelé par `application/pipeline/normalize/normalize_scanr.py`. Regroupe
les UPSERT sur `source_publications`, `source_persons`, `source_authorships`
et la lecture idempotence.
"""

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.db.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


def upsert_scanr_source_publication(
    conn: Connection,
    *,
    scanr_id: str,
    doi: str | None,
    title: str,
    pub_year: int | None,
    doc_type: str | None,
    publication_id: int | None,
    staging_id: int,
    external_ids: Any,
    journal_id: int | None,
    oa_status: str | None,
    language: str | None,
    container_title: str | None,
    abstract: str | None,
    keywords: list[str] | None,
    topics: Any,
    cited_by_count: int | None,
    urls: list[str] | None,
) -> int:
    """UPSERT d'un document ScanR dans `source_publications`. Retourne l'id."""
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, topics, cited_by_count, urls)
        VALUES ('scanr', :scanr_id, :doi, :title, :pub_year, :doc_type,
                :publication_id, :staging_id, :external_ids,
                :journal_id, :oa_status, :language, :container_title,
                :abstract, :keywords, :topics, :cited_by_count, :urls)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doi = COALESCE(source_publications.doi, EXCLUDED.doi),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls)
        RETURNING id
    """).bindparams(
        bindparam("external_ids", type_=JSONB),
        bindparam("topics", type_=JSONB),
    )
    row = conn.execute(
        stmt,
        {
            "scanr_id": scanr_id,
            "doi": doi,
            "title": title,
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
            "topics": topics,
            "cited_by_count": cited_by_count,
            "urls": urls,
        },
    ).one()
    return row.id


def upsert_scanr_source_person_by_idref(
    conn: Connection,
    *,
    idref: str,
    full_name: str,
    orcid: str | None,
) -> int:
    """UPSERT d'un `source_persons` ScanR dédupliqué sur `idref`."""
    row = conn.execute(
        text("""
            INSERT INTO source_persons
                (source, source_id, full_name, orcid, idref)
            VALUES ('scanr', :source_id, :full_name, :orcid, :idref)
            ON CONFLICT (source, source_id) DO UPDATE SET
                orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
                full_name = EXCLUDED.full_name,
                idref = COALESCE(source_persons.idref, EXCLUDED.idref)
            RETURNING id
        """),
        {"source_id": idref, "full_name": full_name, "orcid": orcid, "idref": idref},
    ).one()
    return row.id


def upsert_scanr_source_authorship(
    conn: Connection,
    *,
    source_publication_id: int,
    source_person_id: int | None,
    author_position: int,
    roles: list[str] | None,
    raw_author_name: str | None,
    identifiers: Any,
) -> int:
    """UPSERT d'une `source_authorships` ScanR. Retourne l'id.

    `source_person_id` peut être NULL : depuis le chantier source_persons,
    seuls les auteurs avec idref génèrent un row dans `source_persons`.
    Les autres écrivent uniquement la `source_authorships` avec
    `identifiers={"orcid": ...}` (et éventuellement `idref` si présent
    sans qu'on ait jugé utile de créer un source_persons).
    """
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position, roles,
             author_name_normalized, raw_author_name, identifiers)
        VALUES ('scanr', :spid, :source_person_id, :pos, :roles,
                normalize_name_form(:raw_author_name), :raw_author_name, :identifiers)
        ON CONFLICT (source_publication_id, source_person_id, author_position) DO UPDATE SET
            author_name_normalized = EXCLUDED.author_name_normalized,
            roles = EXCLUDED.roles,
            raw_author_name = EXCLUDED.raw_author_name,
            identifiers = EXCLUDED.identifiers
        RETURNING id
    """).bindparams(bindparam("identifiers", type_=JSONB))
    row = conn.execute(
        stmt,
        {
            "spid": source_publication_id,
            "source_person_id": source_person_id,
            "pos": author_position,
            "roles": roles,
            "raw_author_name": raw_author_name,
            "identifiers": identifiers,
        },
    ).one()
    return row.id


def get_scanr_publication_id(conn: Connection, scanr_id: str) -> int | None:
    """Idempotence : retourne `publication_id` déjà associé au document ScanR."""
    row = conn.execute(
        text(
            "SELECT publication_id FROM source_publications "
            "WHERE source = 'scanr' AND source_id = :scanr_id"
        ),
        {"scanr_id": scanr_id},
    ).one_or_none()
    return row.publication_id if row else None


class PgScanrNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_scanr.ScanrNormalizeQueries`."""

    def upsert_scanr_source_publication(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_scanr_source_publication(conn, **kwargs)

    def upsert_scanr_source_person_by_idref(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_scanr_source_person_by_idref(conn, **kwargs)

    def upsert_scanr_source_authorship(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_scanr_source_authorship(conn, **kwargs)

    def get_scanr_publication_id(self, conn: Connection, scanr_id: str) -> int | None:
        return get_scanr_publication_id(conn, scanr_id)

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)
