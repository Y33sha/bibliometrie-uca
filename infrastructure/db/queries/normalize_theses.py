"""Query service : SQL du normaliseur theses.fr.

Appelé par `application/pipeline/normalize/normalize_theses.py`. Regroupe
les UPSERT sur `source_publications` et `source_authorships`, ainsi
que les lectures utiles à l'idempotence et au matching auteurs.
"""

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.json_types import JsonValue
from domain.persons.name_matching import parse_raw_author_name
from infrastructure.db.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


def fetch_thesis_primary_author(conn: Connection, publication_id: int) -> tuple[str, str] | None:
    """Retourne `(last_name, first_name)` de l'auteur principal d'une thèse existante.

    Rôle `author`, tri par (source_publication_id, author_position), 1 ligne max.
    Lit `source_authorships.raw_author_name` et le parse via
    `domain.names.parse_raw_author_name` (gère « Nom, Prénom » comme
    « Prénom Nom »).
    """
    row = conn.execute(
        text("""
            SELECT sas.raw_author_name
            FROM source_authorships sas
            JOIN source_publications sd ON sd.id = sas.source_publication_id
            WHERE sd.publication_id = :pid
              AND 'author' = ANY(sas.roles)
            ORDER BY sd.id, sas.author_position
            LIMIT 1
        """),
        {"pid": publication_id},
    ).one_or_none()
    if row is None or not row.raw_author_name:
        return None
    last, first = parse_raw_author_name(row.raw_author_name)
    return (last, first) if last else None


def merge_publication_meta(conn: Connection, publication_id: int, meta_json: JsonValue) -> None:
    """Fusionne `publications.meta` avec `meta_json` (concat JSONB)."""
    stmt = text("""
        UPDATE publications
        SET meta = COALESCE(meta, '{}') || :meta_json, updated_at = now()
        WHERE id = :pid
    """).bindparams(bindparam("meta_json", type_=JSONB))
    conn.execute(stmt, {"meta_json": meta_json, "pid": publication_id})


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
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             keywords, topics, meta)
        VALUES ('theses', :theses_id, :doi, :title, :pub_year, :doc_type,
                :publication_id, :staging_id, :external_ids,
                :journal_id, :oa_status, :language, :container_title,
                :keywords, :topics_json, :source_meta_json)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            meta = COALESCE(EXCLUDED.meta, source_publications.meta)
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


def get_theses_publication_id(conn: Connection, theses_id: str) -> int | None:
    """Idempotence : retourne le `publication_id` existant pour un document theses.fr."""
    row = conn.execute(
        text(
            "SELECT publication_id FROM source_publications "
            "WHERE source = 'theses' AND source_id = :theses_id"
        ),
        {"theses_id": theses_id},
    ).one_or_none()
    return row.publication_id if row else None


def count_theses_table(conn: Connection, table: str) -> int:
    """Compte les lignes d'une table avec `source = 'theses'`.

    `table` est une valeur littérale contrôlée par le code appelant (liste blanche).
    """
    if table not in ("source_publications", "source_authorships"):
        raise ValueError(f"Table inattendue : {table!r}")
    return conn.execute(
        text(f"SELECT COUNT(*) AS cnt FROM {table} WHERE source = 'theses'")
    ).scalar_one()


class PgThesesNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_theses.ThesesNormalizeQueries`."""

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None:
        return fetch_thesis_primary_author(conn, publication_id)

    def merge_publication_meta(
        self, conn: Connection, publication_id: int, meta_json: JsonValue
    ) -> None:
        merge_publication_meta(conn, publication_id, meta_json)

    def upsert_theses_source_publication(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_theses_source_publication(conn, **kwargs)

    def upsert_theses_source_authorship(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_theses_source_authorship(conn, **kwargs)

    def get_theses_publication_id(self, conn: Connection, theses_id: str) -> int | None:
        return get_theses_publication_id(conn, theses_id)

    def count_theses_table(self, conn: Connection, table: str) -> int:
        return count_theses_table(conn, table)

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)
