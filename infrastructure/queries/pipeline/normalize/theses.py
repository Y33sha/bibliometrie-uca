"""Query service : SQL du normaliseur theses.fr.

Appelé par `application/pipeline/normalize/normalize_theses.py`. Regroupe
les UPSERT sur `source_publications` et `source_authorships`, ainsi
que les lectures utiles à l'idempotence et au matching auteurs.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.theses import ThesesNormalizeQueries
from domain.publications.metadata import normalized_title
from domain.types import JsonValue
from infrastructure.queries.pipeline.source_authorships import (
    clear_source_authorships_for_publication,
)


def upsert_theses_source_publication(
    conn: Connection,
    *,
    theses_id: str,
    doi: str | None,
    title: str,
    pub_year: int | None,
    doc_type: str,
    publication_id: int | None,
    staging_id: int,
    external_ids: JsonValue,
    journal_id: int | None,
    oa_status: str | None,
    language: str | None,
    container_title: str | None,
    keywords: list[str] | None,
    topics_json: JsonValue,
    source_meta_json: JsonValue,
) -> int:
    """UPSERT d'un document theses.fr dans `source_publications`."""
    # cf. note dans normalize_openalex : `external_ids` non-null en colonne,
    # on substitue None → {} avant binding.
    if external_ids is None:
        external_ids = {}
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, doi, title, title_normalized, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             keywords, topics, meta)
        VALUES ('theses', :theses_id, :doi, :title, :title_normalized, :pub_year, :doc_type,
                :publication_id, :staging_id, :external_ids,
                :journal_id, :oa_status, :language, :container_title,
                :keywords, :topics_json, :source_meta_json)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            external_ids = source_publications.external_ids || EXCLUDED.external_ids,
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            meta = COALESCE(EXCLUDED.meta, source_publications.meta),
            updated_at = clock_timestamp()
        RETURNING id
    """).bindparams(
        bindparam("external_ids", type_=JSONB),
        bindparam("topics_json", type_=JSONB),
        bindparam("source_meta_json", type_=JSONB),
    )
    row = conn.execute(
        stmt,
        {
            "theses_id": theses_id,
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
            "keywords": keywords,
            "topics_json": topics_json,
            "source_meta_json": source_meta_json,
        },
    ).one()
    return row.id


def upsert_theses_source_authorship(
    conn: Connection,
    *,
    source_publication_id: int,
    author_position: int | None,
    roles: list[str],
    raw_author_name: str,
    person_identifiers: JsonValue,
) -> int:
    """UPSERT d'une `source_authorships` theses.fr. `author_position` NULL pour les non-auteurs.

    Les identifiants (PPN/idref) vivent sur `person_identifiers` (JSONB).
    """
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, author_position,
             author_name_normalized, roles,
             raw_author_name, person_identifiers)
        VALUES ('theses', :spid, :pos,
                normalize_name_form(:raw_author_name), :roles,
                :raw_author_name, :person_identifiers)
        ON CONFLICT (source_publication_id, author_position) DO UPDATE SET
            roles = EXCLUDED.roles,
            author_name_normalized = EXCLUDED.author_name_normalized,
            raw_author_name = EXCLUDED.raw_author_name,
            person_identifiers = EXCLUDED.person_identifiers
        RETURNING id
    """).bindparams(bindparam("person_identifiers", type_=JSONB))
    row = conn.execute(
        stmt,
        {
            "spid": source_publication_id,
            "pos": author_position,
            "roles": roles,
            "raw_author_name": raw_author_name,
            "person_identifiers": person_identifiers,
        },
    ).one()
    return row.id


def count_theses_table(conn: Connection, table: str) -> int:
    """Compte les lignes d'une table avec `source = 'theses'`.

    `table` est une valeur littérale contrôlée par le code appelant (liste blanche).
    """
    if table not in ("source_publications", "source_authorships"):
        raise ValueError(f"Table inattendue : {table!r}")
    return conn.execute(
        text(f"SELECT COUNT(*) AS cnt FROM {table} WHERE source = 'theses'")
    ).scalar_one()


class PgThesesNormalizeQueries(ThesesNormalizeQueries):
    """Adapter PostgreSQL pour `application.ports.normalize_theses.ThesesNormalizeQueries`."""

    def upsert_theses_source_publication(
        self,
        conn: Connection,
        *,
        theses_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str,
        publication_id: int | None,
        staging_id: int,
        external_ids: JsonValue,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        keywords: list[str] | None,
        topics_json: JsonValue,
        source_meta_json: JsonValue,
    ) -> int:
        return upsert_theses_source_publication(
            conn,
            theses_id=theses_id,
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
            keywords=keywords,
            topics_json=topics_json,
            source_meta_json=source_meta_json,
        )

    def upsert_theses_source_authorship(
        self,
        conn: Connection,
        *,
        source_publication_id: int,
        author_position: int | None,
        roles: list[str],
        raw_author_name: str,
        person_identifiers: JsonValue,
    ) -> int:
        return upsert_theses_source_authorship(
            conn,
            source_publication_id=source_publication_id,
            author_position=author_position,
            roles=roles,
            raw_author_name=raw_author_name,
            person_identifiers=person_identifiers,
        )

    def count_theses_table(self, conn: Connection, table: str) -> int:
        return count_theses_table(conn, table)

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)
