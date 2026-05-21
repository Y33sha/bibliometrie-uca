"""Query service : SQL du normaliseur HAL.

Appelé par `application/pipeline/normalize/normalize_hal.py`. Regroupe
les UPSERT sur `source_publications` et `source_authorships`, ainsi
que les lectures d'idempotence.

Les identifiants personne (orcid/idhal/idref/hal_person_id) vivent sur
`sa.person_identifiers` (JSONB) et les IDs natifs des structures HAL
(`halId_s`) sur `sa.source_structures` (TEXT[]).
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.hal import HalNormalizeQueries
from domain.json_types import JsonValue
from infrastructure.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


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
            (source, source_id, doi, title, pub_year, doc_type,
             hal_collections, publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, topics, biblio, urls)
        VALUES ('hal', :hal_id, :doi, :title, :pub_year, :doc_type,
                :hal_collections, :publication_id, :staging_id, :external_ids,
                :journal_id, :oa_status, :language, :container_title,
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
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls),
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
            "pub_year": pub_year,
            "doc_type": doc_type,
            "hal_collections": hal_collections,
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
            "biblio": biblio,
            "urls": urls,
        },
    ).one()
    return row.id


def upsert_hal_source_authorship(
    conn: Connection,
    *,
    source_publication_id: int,
    author_position: int,
    source_structures: list[str] | None,
    raw_author_name: str,
    is_corresponding: bool,
    roles: list[str] | None,
    person_identifiers: JsonValue,
) -> int:
    """UPSERT d'une `source_authorships` HAL.

    Les identifiants personne (`orcid`/`idref`/`idhal`/`hal_person_id`)
    vivent sur `person_identifiers` (JSONB).

    `source_structures` (TEXT[]) stocke les `halId_s` natifs des
    structures référencées par cette authorship.
    """
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, author_position, source_structures,
             author_name_normalized, is_corresponding, roles, raw_author_name, person_identifiers)
        VALUES ('hal', :spid, :pos, :source_structures,
                normalize_name_form(:raw_author_name), :is_corresponding, :roles,
                :raw_author_name, :person_identifiers)
        ON CONFLICT (source_publication_id, author_position) DO UPDATE SET
            source_structures = COALESCE(
                EXCLUDED.source_structures,
                source_authorships.source_structures
            ),
            author_name_normalized = EXCLUDED.author_name_normalized,
            is_corresponding = EXCLUDED.is_corresponding,
            roles = EXCLUDED.roles,
            raw_author_name = EXCLUDED.raw_author_name,
            person_identifiers = EXCLUDED.person_identifiers
        RETURNING id
    """).bindparams(bindparam("person_identifiers", type_=JSONB))
    row = conn.execute(
        stmt,
        {
            "spid": source_publication_id,
            "pos": author_position,
            "source_structures": source_structures,
            "raw_author_name": raw_author_name,
            "is_corresponding": is_corresponding,
            "roles": roles,
            "person_identifiers": person_identifiers,
        },
    ).one()
    return row.id


def staging_has_hal_doi(conn: Connection, doi: str) -> bool:
    """Vrai si le DOI est déjà présent dans `staging` pour `source='hal'` (dédup Zenodo)."""
    return (
        conn.execute(
            text("SELECT id FROM staging WHERE source = 'hal' AND lower(doi) = lower(:doi)"),
            {"doi": doi},
        ).first()
        is not None
    )


class PgHalNormalizeQueries(HalNormalizeQueries):
    """Adapter PostgreSQL pour `application.ports.normalize_hal.HalNormalizeQueries`."""

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
            language=language,
            container_title=container_title,
            abstract=abstract,
            keywords=keywords,
            topics=topics,
            biblio=biblio,
            urls=urls,
        )

    def upsert_hal_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        author_position: int,
        source_structures: list[str] | None,
        raw_author_name: str,
        is_corresponding: bool,
        roles: list[str] | None,
        person_identifiers: JsonValue,
    ) -> int:
        return upsert_hal_source_authorship(
            conn,
            source_publication_id=source_publication_id,
            author_position=author_position,
            source_structures=source_structures,
            raw_author_name=raw_author_name,
            is_corresponding=is_corresponding,
            roles=roles,
            person_identifiers=person_identifiers,
        )

    def staging_has_hal_doi(self, conn: Connection, doi: str) -> bool:
        return staging_has_hal_doi(conn, doi)

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)
