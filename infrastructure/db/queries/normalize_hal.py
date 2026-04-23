"""Query service : SQL du normaliseur HAL.

Appelé par `application/pipeline/normalize/normalize_hal.py`. Regroupe les
UPSERT sur `source_publications`, `source_persons`, `source_structures`,
`source_authorships`, ainsi que les lectures d'idempotence et les
cleanups de post-traitement (doublons de position, persons orphelins).
"""

from typing import Any

from infrastructure.db.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


def upsert_hal_source_publication(
    cur: Any,
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
    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             hal_collections, publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, topics, biblio, urls)
        VALUES ('hal', %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s)
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
        """,
        (
            hal_id,
            doi,
            title,
            pub_year,
            doc_type,
            hal_collections,
            publication_id,
            staging_id,
            external_ids,
            journal_id,
            oa_status,
            language,
            container_title,
            abstract,
            keywords,
            topics,
            biblio,
            urls,
        ),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def upsert_hal_source_person(
    cur: Any,
    *,
    source_id: str,
    full_name: str,
    last_name: str,
    first_name: str | None,
    orcid: str | None,
    idref: str | None,
    source_ids_json: Any,
) -> int:
    """UPSERT d'un `source_persons` HAL. Commune aux passes hal_person_id/form_id."""
    cur.execute(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name, orcid, idref,
             source_ids)
        VALUES ('hal', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
            idref = COALESCE(source_persons.idref, EXCLUDED.idref),
            full_name = EXCLUDED.full_name,
            source_ids = COALESCE(source_persons.source_ids, '{}') ||
                         COALESCE(EXCLUDED.source_ids, '{}')
        RETURNING id
        """,
        (source_id, full_name, last_name, first_name, orcid, idref, source_ids_json),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def find_hal_source_person_nokey(cur: Any, *, full_name: str, first_name: str | None) -> int | None:
    """Cherche un `source_persons` HAL sans identifiant par nom exact."""
    cur.execute(
        """
        SELECT id FROM source_persons
        WHERE source = 'hal'
          AND source_id LIKE 'nokey-%%'
          AND full_name = %s
          AND first_name IS NOT DISTINCT FROM %s
        LIMIT 1
        """,
        (full_name, first_name),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row[0] if isinstance(row, tuple) else row["id"]


def enrich_hal_source_person(
    cur: Any,
    *,
    source_person_id: int,
    orcid: str | None,
    idref: str | None,
    source_ids_json: Any,
) -> None:
    """Ajoute `orcid` / `idref` / `source_ids` sur un `source_persons` HAL existant (nokey)."""
    cur.execute(
        """
        UPDATE source_persons SET
            orcid = COALESCE(source_persons.orcid, %s),
            idref = COALESCE(source_persons.idref, %s),
            source_ids = COALESCE(source_persons.source_ids, '{}') ||
                         COALESCE(%s::jsonb, '{}')
        WHERE id = %s
        """,
        (orcid, idref, source_ids_json, source_person_id),
    )


def insert_hal_source_person_new(
    cur: Any,
    *,
    full_name: str,
    last_name: str,
    first_name: str | None,
    orcid: str | None,
    idref: str | None,
    source_ids_json: Any,
) -> int:
    """Crée un `source_persons` HAL sans identifiant (source_id = `nokey-<seq>`)."""
    cur.execute("SELECT nextval('source_persons_id_seq')")
    row = cur.fetchone()
    next_id = row[0] if isinstance(row, tuple) else row["nextval"]
    src_id = f"nokey-{next_id}"
    cur.execute(
        """
        INSERT INTO source_persons
            (id, source, source_id, full_name, last_name, first_name, orcid, idref,
             source_ids)
        VALUES (%s, 'hal', %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (next_id, src_id, full_name, last_name, first_name, orcid, idref, source_ids_json),
    )
    inserted = cur.fetchone()
    return inserted[0] if isinstance(inserted, tuple) else inserted["id"]


def upsert_hal_source_structure(cur: Any, *, source_id: str, name: str) -> int:
    """UPSERT d'une `source_structures` HAL à la volée (parse de `authIdHasStructure_fs`)."""
    cur.execute(
        """
        INSERT INTO source_structures (source, source_id, name)
        VALUES ('hal', %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            name = COALESCE(NULLIF(source_structures.name, ''), EXCLUDED.name)
        RETURNING id
        """,
        (source_id, name),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def fetch_hal_source_structure_ids(cur: Any, source_ids: list[str]) -> list[int]:
    """Retourne les `id` des `source_structures` HAL pour une liste de `source_id`."""
    cur.execute(
        """
        SELECT id FROM source_structures
        WHERE source = 'hal' AND source_id = ANY(%s)
        """,
        (source_ids,),
    )
    return [r[0] if isinstance(r, tuple) else r["id"] for r in cur.fetchall()]


def upsert_hal_source_authorship(
    cur: Any,
    *,
    source_publication_id: int,
    source_person_id: int,
    author_position: int,
    source_struct_ids: list[int] | None,
    raw_author_name: str,
    is_corresponding: bool,
    roles: list[str] | None,
) -> int:
    """UPSERT d'une `source_authorships` HAL (inclut `source_struct_ids`)."""
    cur.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position, source_struct_ids,
             author_name_normalized, is_corresponding, roles, raw_author_name)
        VALUES ('hal', %s, %s, %s, %s, normalize_name_form(%s), %s, %s, %s)
        ON CONFLICT (source_publication_id, source_person_id, author_position) DO UPDATE SET
            source_struct_ids = COALESCE(
                EXCLUDED.source_struct_ids,
                source_authorships.source_struct_ids
            ),
            author_name_normalized = EXCLUDED.author_name_normalized,
            is_corresponding = EXCLUDED.is_corresponding,
            roles = EXCLUDED.roles,
            raw_author_name = EXCLUDED.raw_author_name
        RETURNING id
        """,
        (
            source_publication_id,
            source_person_id,
            author_position,
            source_struct_ids,
            raw_author_name,
            is_corresponding,
            roles,
            raw_author_name,
        ),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def staging_has_hal_doi(cur: Any, doi: str) -> bool:
    """Vrai si le DOI est déjà présent dans `staging` pour `source='hal'` (dédup Zenodo)."""
    cur.execute(
        "SELECT id FROM staging WHERE source = 'hal' AND lower(doi) = lower(%s)",
        (doi,),
    )
    return cur.fetchone() is not None


def get_hal_publication_id(cur: Any, hal_id: str) -> int | None:
    """Idempotence : retourne `publication_id` déjà associé au document HAL."""
    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'hal' AND source_id = %s",
        (hal_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    pid = row[0] if isinstance(row, tuple) else row["publication_id"]
    return pid if pid else None


def fetch_hal_source_structures_for_cache(cur: Any) -> list[tuple[str, int, str]]:
    """Charge `(source_id, id, name)` des `source_structures` HAL pour préchargement cache."""
    cur.execute("""
        SELECT source_id, id, COALESCE(name, '')
        FROM source_structures WHERE source = 'hal'
    """)
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def delete_hal_duplicate_authorship_addresses(cur: Any) -> None:
    """Post-traitement : supprime les `source_authorship_addresses` des doublons de position."""
    cur.execute("""
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


def delete_hal_duplicate_authorships(cur: Any) -> int:
    """Supprime les `source_authorships` HAL en doublon de position (garde le + récent).

    Retourne le nombre de lignes supprimées.
    """
    cur.execute("""
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
    return cur.rowcount


def delete_hal_orphan_source_persons(cur: Any) -> int:
    """Supprime les `source_persons` HAL sans aucune `source_authorships` (orphelins)."""
    cur.execute("""
        DELETE FROM source_persons
        WHERE source = 'hal'
          AND NOT EXISTS (
              SELECT 1 FROM source_authorships sa
              WHERE sa.source_person_id = source_persons.id
          )
    """)
    return cur.rowcount


class PgHalNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_hal.HalNormalizeQueries`."""

    def upsert_hal_source_publication(self, cur: Any, **kwargs: Any) -> int:
        return upsert_hal_source_publication(cur, **kwargs)

    def upsert_hal_source_person(self, cur: Any, **kwargs: Any) -> int:
        return upsert_hal_source_person(cur, **kwargs)

    def find_hal_source_person_nokey(
        self, cur: Any, *, full_name: str, first_name: str | None
    ) -> int | None:
        return find_hal_source_person_nokey(cur, full_name=full_name, first_name=first_name)

    def enrich_hal_source_person(
        self,
        cur: Any,
        *,
        source_person_id: int,
        orcid: str | None,
        idref: str | None,
        source_ids_json: Any,
    ) -> None:
        enrich_hal_source_person(
            cur,
            source_person_id=source_person_id,
            orcid=orcid,
            idref=idref,
            source_ids_json=source_ids_json,
        )

    def insert_hal_source_person_new(self, cur: Any, **kwargs: Any) -> int:
        return insert_hal_source_person_new(cur, **kwargs)

    def upsert_hal_source_structure(self, cur: Any, *, source_id: str, name: str) -> int:
        return upsert_hal_source_structure(cur, source_id=source_id, name=name)

    def fetch_hal_source_structure_ids(self, cur: Any, source_ids: list[str]) -> list[int]:
        return fetch_hal_source_structure_ids(cur, source_ids)

    def upsert_hal_source_authorship(self, cur: Any, **kwargs: Any) -> int:
        return upsert_hal_source_authorship(cur, **kwargs)

    def staging_has_hal_doi(self, cur: Any, doi: str) -> bool:
        return staging_has_hal_doi(cur, doi)

    def get_hal_publication_id(self, cur: Any, hal_id: str) -> int | None:
        return get_hal_publication_id(cur, hal_id)

    def fetch_hal_source_structures_for_cache(self, cur: Any) -> list[tuple[str, int, str]]:
        return fetch_hal_source_structures_for_cache(cur)

    def delete_hal_duplicate_authorship_addresses(self, cur: Any) -> None:
        delete_hal_duplicate_authorship_addresses(cur)

    def delete_hal_duplicate_authorships(self, cur: Any) -> int:
        return delete_hal_duplicate_authorships(cur)

    def delete_hal_orphan_source_persons(self, cur: Any) -> int:
        return delete_hal_orphan_source_persons(cur)

    def clear_source_authorships_for_publication(
        self, cur: Any, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(cur, source_publication_id)
