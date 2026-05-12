"""Query service : SQL du normaliseur Web of Science.

Appelé par `application/pipeline/normalize/normalize_wos.py`. Regroupe les
UPSERT batch (via SA executemany) sur `source_persons`,
`source_structures`, `source_authorships`, `source_authorship_addresses`,
et les lectures/préchargements de caches.
"""

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.json_types import JsonValue
from infrastructure.db.queries.source_authorships import (
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
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}')
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


def upsert_wos_source_structure(conn: Connection, *, name: str, ror_id: str | None) -> int:
    """UPSERT d'une `source_structures` WoS (source_id = name)."""
    row = conn.execute(
        text("""
            INSERT INTO source_structures (source, source_id, name, ror_id)
            VALUES ('wos', :source_id, :name, :ror_id)
            ON CONFLICT (source, source_id) DO UPDATE SET
                ror_id = COALESCE(source_structures.ror_id, EXCLUDED.ror_id)
            RETURNING id
        """),
        {"source_id": name, "name": name, "ror_id": ror_id},
    ).one()
    return row.id


def upsert_addresses_batch(conn: Connection, values: list[dict[str, Any]]) -> None:
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


def upsert_wos_source_authorships_batch(conn: Connection, values: list[dict[str, Any]]) -> None:
    """Batch UPSERT de `source_authorships` WoS.

    Chaque dict du batch a les clés : ``source_publication_id``,
    ``source_person_id`` (toujours None), ``author_position``,
    ``is_corresponding``, ``author_name_normalized``,
    ``source_struct_ids``, ``roles``, ``raw_author_name``, ``identifiers``.

    `source_person_id` est NULL : depuis le chantier source_persons, WoS
    n'écrit plus dans `source_persons` (entité algorithmique non fiable
    via `daisng_id`). Les identifiants normalisés (`orcid`, `researcher_id`)
    vivent sur `identifiers`.
    """
    if not values:
        return
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             is_corresponding, author_name_normalized,
             source_struct_ids, roles, raw_author_name, identifiers)
        VALUES ('wos', :spid, :source_person_id, :author_position,
                :is_corresponding, :author_name_normalized,
                :source_struct_ids, :roles, :raw_author_name, :identifiers)
        ON CONFLICT (source_publication_id, source_person_id, author_position) DO UPDATE SET
            is_corresponding = EXCLUDED.is_corresponding OR source_authorships.is_corresponding,
            author_name_normalized = COALESCE(
                EXCLUDED.author_name_normalized,
                source_authorships.author_name_normalized
            ),
            source_struct_ids = COALESCE(
                EXCLUDED.source_struct_ids,
                source_authorships.source_struct_ids
            ),
            roles = EXCLUDED.roles,
            raw_author_name = EXCLUDED.raw_author_name,
            identifiers = EXCLUDED.identifiers
    """).bindparams(
        bindparam("identifiers", type_=JSONB),
    )
    conn.execute(stmt, values)


def fetch_source_authorship_ids_by_position(
    conn: Connection, *, source_publication_id: int, positions: list[int]
) -> dict[int, int]:
    """Retourne `{author_position: source_authorship_id}` pour un document WoS.

    Pivot par `author_position` (et non plus `source_person_id`) parce que
    WoS n'alimente plus `source_persons` (cf. chantier source_persons).
    """
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
    conn: Connection, values: list[dict[str, int]]
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


def get_wos_publication_id(conn: Connection, ut: str) -> int | None:
    """Idempotence : retourne le `publication_id` déjà associé au document WoS."""
    row = conn.execute(
        text(
            "SELECT publication_id FROM source_publications "
            "WHERE source = 'wos' AND source_id = :ut"
        ),
        {"ut": ut},
    ).one_or_none()
    if row is None:
        return None
    return row.publication_id if row.publication_id else None


def fetch_wos_source_structures(conn: Connection) -> list[tuple[str, int]]:
    """Charge `(source_id, id)` des `source_structures` WoS (préchargement cache)."""
    rows = conn.execute(
        text("SELECT source_id, id FROM source_structures WHERE source = 'wos'")
    ).all()
    return [(r.source_id, r.id) for r in rows]


def delete_wos_duplicate_authorships(conn: Connection) -> int:
    """Supprime les `source_authorships` WoS en doublon de position.

    WoS renvoie parfois 2 entrées `name` au même `seq_no` pour les publis
    consortium (ATLAS/CERN) : typiquement 1 avec un `daisng_id` renseigné
    et 1 héritée d'un ancien code sans `daisng_id` (source_id synthétique
    `wos-XXXX`). Le parseur actuel n'y crée plus ce cas (cf. filter
    `if not daisng_id: continue`), mais les rows historiques subsistent.

    Heuristique : on garde la row dont le ``source_persons`` a un
    ``daisng_id`` (``source_id NOT LIKE 'wos-%'``). À égalité
    (deux daisng_id, auteur désambiguïsé deux fois côté WoS), on garde
    la row la plus récente (``id`` max). Retourne le nombre de lignes
    supprimées.
    """
    return conn.execute(
        text("""
            WITH ranked AS (
                SELECT sa.id,
                       ROW_NUMBER() OVER (
                           PARTITION BY sa.source_publication_id, sa.author_position
                           ORDER BY
                               (sp.source_id LIKE 'wos-%') ASC,
                               sa.id DESC
                       ) AS rn
                FROM source_authorships sa
                JOIN source_persons sp ON sp.id = sa.source_person_id
                WHERE sa.source = 'wos' AND sa.author_position IS NOT NULL
            )
            DELETE FROM source_authorships
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """)
    ).rowcount


class PgWosNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_wos.WosNormalizeQueries`."""

    def upsert_wos_source_publication(self, conn: Connection, **kwargs: Any) -> int:
        return upsert_wos_source_publication(conn, **kwargs)

    def upsert_wos_source_structure(
        self, conn: Connection, *, name: str, ror_id: str | None
    ) -> int:
        return upsert_wos_source_structure(conn, name=name, ror_id=ror_id)

    def upsert_addresses_batch(self, conn: Connection, values: list[dict[str, Any]]) -> None:
        upsert_addresses_batch(conn, values)

    def fetch_address_ids_by_raw_text(
        self, conn: Connection, raw_texts: list[str]
    ) -> dict[str, int]:
        return fetch_address_ids_by_raw_text(conn, raw_texts)

    def upsert_wos_source_authorships_batch(
        self, conn: Connection, values: list[dict[str, Any]]
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
        self, conn: Connection, values: list[dict[str, int]]
    ) -> None:
        insert_source_authorship_addresses_batch(conn, values)

    def get_wos_publication_id(self, conn: Connection, ut: str) -> int | None:
        return get_wos_publication_id(conn, ut)

    def fetch_wos_source_structures(self, conn: Connection) -> list[tuple[str, int]]:
        return fetch_wos_source_structures(conn)

    def delete_wos_duplicate_authorships(self, conn: Connection) -> int:
        return delete_wos_duplicate_authorships(conn)

    def clear_source_authorships_for_publication(
        self, conn: Connection, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(conn, source_publication_id)
