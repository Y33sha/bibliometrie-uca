"""Query service : SQL du normaliseur HAL.

Appelé par `application/pipeline/normalize/normalize_hal.py`. Regroupe les
UPSERT sur `source_publications`, `source_persons`, `source_structures`,
`source_authorships`, ainsi que les lectures d'idempotence et les
cleanups de post-traitement (doublons de position, persons orphelins).
"""

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.db.queries.source_authorships import (
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
    external_ids: Any,
    journal_id: int | None,
    oa_status: str | None,
    language: str | None,
    container_title: str | None,
    abstract: str | None,
    keywords: list[str] | None,
    topics: Any,
    biblio: Any,
    urls: list[str] | None,
) -> int:
    """UPSERT d'un document HAL dans `source_publications`."""
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
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls)
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


def upsert_hal_source_person(
    conn: Connection,
    *,
    source_id: str,
    full_name: str,
    orcid: str | None,
    idref: str | None,
    source_ids_json: Any,
) -> int:
    """UPSERT d'un `source_persons` HAL. Commune aux passes hal_person_id/form_id."""
    stmt = text("""
        INSERT INTO source_persons
            (source, source_id, full_name, orcid, idref, source_ids)
        VALUES ('hal', :source_id, :full_name, :orcid, :idref, :source_ids)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
            idref = COALESCE(source_persons.idref, EXCLUDED.idref),
            full_name = EXCLUDED.full_name,
            source_ids = COALESCE(source_persons.source_ids, '{}') ||
                         COALESCE(EXCLUDED.source_ids, '{}')
        RETURNING id
    """).bindparams(bindparam("source_ids", type_=JSONB))
    row = conn.execute(
        stmt,
        {
            "source_id": source_id,
            "full_name": full_name,
            "orcid": orcid,
            "idref": idref,
            "source_ids": source_ids_json,
        },
    ).one()
    return row.id


def upsert_hal_source_structure(conn: Connection, *, source_id: str, name: str) -> int:
    """UPSERT d'une `source_structures` HAL à la volée (parse de `authIdHasStructure_fs`)."""
    row = conn.execute(
        text("""
            INSERT INTO source_structures (source, source_id, name)
            VALUES ('hal', :source_id, :name)
            ON CONFLICT (source, source_id) DO UPDATE SET
                name = COALESCE(NULLIF(source_structures.name, ''), EXCLUDED.name)
            RETURNING id
        """),
        {"source_id": source_id, "name": name},
    ).one()
    return row.id


def fetch_hal_source_structure_ids(conn: Connection, source_ids: list[str]) -> list[int]:
    """Retourne les `id` des `source_structures` HAL pour une liste de `source_id`."""
    rows = conn.execute(
        text(
            "SELECT id FROM source_structures WHERE source = 'hal' AND source_id = ANY(:source_ids)"
        ),
        {"source_ids": source_ids},
    ).all()
    return [r.id for r in rows]


def upsert_hal_source_authorship(
    conn: Connection,
    *,
    source_publication_id: int,
    source_person_id: int | None,
    author_position: int,
    source_struct_ids: list[int] | None,
    raw_author_name: str,
    is_corresponding: bool,
    roles: list[str] | None,
    identifiers: Any,
) -> int:
    """UPSERT d'une `source_authorships` HAL (inclut `source_struct_ids`).

    `source_person_id` peut être NULL : depuis le chantier source_persons,
    seuls les auteurs avec `hal_person_id` génèrent un row dans
    `source_persons`. Les autres (sans compte HAL, juste un form_id ou
    rien) écrivent uniquement la `source_authorships` avec `identifiers`
    (orcid / idref / idhal selon disponibilité).
    """
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position, source_struct_ids,
             author_name_normalized, is_corresponding, roles, raw_author_name, identifiers)
        VALUES ('hal', :spid, :source_person_id, :pos, :source_struct_ids,
                normalize_name_form(:raw_author_name), :is_corresponding, :roles,
                :raw_author_name, :identifiers)
        ON CONFLICT (source_publication_id, source_person_id, author_position) DO UPDATE SET
            source_struct_ids = COALESCE(
                EXCLUDED.source_struct_ids,
                source_authorships.source_struct_ids
            ),
            author_name_normalized = EXCLUDED.author_name_normalized,
            is_corresponding = EXCLUDED.is_corresponding,
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
            "source_struct_ids": source_struct_ids,
            "raw_author_name": raw_author_name,
            "is_corresponding": is_corresponding,
            "roles": roles,
            "identifiers": identifiers,
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


def get_hal_publication_id(conn: Connection, hal_id: str) -> int | None:
    """Idempotence : retourne `publication_id` déjà associé au document HAL."""
    row = conn.execute(
        text(
            "SELECT publication_id FROM source_publications "
            "WHERE source = 'hal' AND source_id = :hal_id"
        ),
        {"hal_id": hal_id},
    ).one_or_none()
    if row is None:
        return None
    return row.publication_id if row.publication_id else None


def fetch_hal_source_structures_for_cache(conn: Connection) -> list[tuple[str, int, str]]:
    """Charge `(source_id, id, name)` des `source_structures` HAL pour préchargement cache."""
    rows = conn.execute(
        text("""
            SELECT source_id, id, COALESCE(name, '') AS name
            FROM source_structures WHERE source = 'hal'
        """)
    ).all()
    return [(r.source_id, r.id, r.name) for r in rows]


def delete_hal_duplicate_authorship_addresses(conn: Connection) -> None:
    """Post-traitement : supprime les `source_authorship_addresses` des doublons de position."""
    conn.execute(
        text("""
            DELETE FROM source_authorship_addresses
            WHERE source_authorship_id IN (
                SELECT sa1.id FROM source_authorships sa1
                JOIN source_authorships sa2
                  ON sa2.source_publication_id = sa1.source_publication_id
                 AND sa2.author_position = sa1.author_position
                 AND sa2.id > sa1.id
                WHERE sa1.source = 'hal' AND sa1.author_position IS NOT NULL
            )
        """)
    )


def delete_hal_duplicate_authorships(conn: Connection) -> int:
    """Supprime les `source_authorships` HAL en doublon de position (garde le + récent).

    Retourne le nombre de lignes supprimées.
    """
    return conn.execute(
        text("""
            DELETE FROM source_authorships
            WHERE source = 'hal' AND id IN (
                SELECT sa1.id FROM source_authorships sa1
                JOIN source_authorships sa2
                  ON sa2.source_publication_id = sa1.source_publication_id
                 AND sa2.author_position = sa1.author_position
                 AND sa2.id > sa1.id
                WHERE sa1.source = 'hal' AND sa1.author_position IS NOT NULL
            )
        """)
    ).rowcount


class PgHalNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_hal.HalNormalizeQueries`."""

    def upsert_hal_source_publication(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_hal_source_publication(conn, **kwargs)

    def upsert_hal_source_person(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_hal_source_person(conn, **kwargs)

    def upsert_hal_source_structure(self, conn: Connection, *, source_id: str, name: str) -> int:
        return upsert_hal_source_structure(conn, source_id=source_id, name=name)

    def fetch_hal_source_structure_ids(self, conn: Connection, source_ids: list[str]) -> list[int]:
        return fetch_hal_source_structure_ids(conn, source_ids)

    def upsert_hal_source_authorship(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_hal_source_authorship(conn, **kwargs)

    def staging_has_hal_doi(self, conn: Connection, doi: str) -> bool:
        return staging_has_hal_doi(conn, doi)

    def get_hal_publication_id(self, conn: Connection, hal_id: str) -> int | None:
        return get_hal_publication_id(conn, hal_id)

    def fetch_hal_source_structures_for_cache(self, conn: Connection) -> list[tuple[str, int, str]]:
        return fetch_hal_source_structures_for_cache(conn)

    def delete_hal_duplicate_authorship_addresses(self, conn: Connection) -> None:
        delete_hal_duplicate_authorship_addresses(conn)

    def delete_hal_duplicate_authorships(self, conn: Connection) -> int:
        return delete_hal_duplicate_authorships(conn)

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)
