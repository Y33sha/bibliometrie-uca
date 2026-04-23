"""Query service : SQL du normaliseur theses.fr.

Appelé par `application/pipeline/normalize/normalize_theses.py`. Regroupe
les UPSERT sur `source_publications`, `source_persons`, `source_authorships`
ainsi que les lectures utiles à l'idempotence et au matching auteurs.
"""

from typing import Any

from infrastructure.db.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


def fetch_thesis_primary_author(cur: Any, publication_id: int) -> tuple[str, str] | None:
    """Retourne `(last_name, first_name)` de l'auteur principal d'une thèse existante.

    Rôle `author`, tri par (source_publication_id, author_position), 1 ligne max.
    """
    cur.execute(
        """
        SELECT sa.last_name, sa.first_name
        FROM source_authorships sas
        JOIN source_publications sd ON sd.id = sas.source_publication_id
        JOIN source_persons sa ON sa.id = sas.source_person_id
        WHERE sd.publication_id = %s
          AND 'author' = ANY(sas.roles)
        ORDER BY sd.id, sas.author_position
        LIMIT 1
        """,
        (publication_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return row["last_name"] or "", row["first_name"] or ""
    return row[0] or "", row[1] or ""


def merge_publication_meta(cur: Any, publication_id: int, meta_json: Any) -> None:
    """Fusionne `publications.meta` avec `meta_json` (concat JSONB)."""
    cur.execute(
        """
        UPDATE publications
        SET meta = COALESCE(meta, '{}') || %s, updated_at = now()
        WHERE id = %s
        """,
        (meta_json, publication_id),
    )


def upsert_theses_source_publication(
    cur: Any,
    *,
    theses_id: str,
    doi: str | None,
    title: str,
    pub_year: int | None,
    doc_type: str,
    publication_id: int | None,
    staging_id: int,
    external_ids: Any,
    journal_id: int | None,
    oa_status: str | None,
    language: str | None,
    container_title: str | None,
    keywords: list[str] | None,
    topics_json: Any,
    source_meta_json: Any,
) -> int:
    """UPSERT d'un document theses.fr dans `source_publications`."""
    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             keywords, topics, meta)
        VALUES ('theses', %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s)
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
        """,
        (
            theses_id,
            doi,
            title,
            pub_year,
            doc_type,
            publication_id,
            staging_id,
            external_ids,
            journal_id,
            oa_status,
            language,
            container_title,
            keywords,
            topics_json,
            source_meta_json,
        ),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_theses_source_person_by_ppn(
    cur: Any, *, ppn: str, full_name: str, last_name: str, first_name: str | None
) -> int:
    """UPSERT d'un `source_persons` theses.fr dédupliqué sur PPN (idref)."""
    cur.execute(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name, idref)
        VALUES ('theses', %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            idref = COALESCE(source_persons.idref, EXCLUDED.idref)
        RETURNING id
        """,
        (ppn, full_name, last_name, first_name, ppn),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def find_theses_source_person_by_name(
    cur: Any, *, full_name: str, first_name: str | None
) -> int | None:
    """Cherche un `source_persons` theses.fr (sans PPN) par nom exact."""
    cur.execute(
        """
        SELECT id FROM source_persons
        WHERE source = 'theses'
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
    return row["id"] if isinstance(row, dict) else row[0]


def insert_theses_source_person_new(
    cur: Any, *, full_name: str, last_name: str, first_name: str | None
) -> int:
    """Crée un nouveau `source_persons` theses.fr sans PPN, `source_id = nokey-<seq>`."""
    cur.execute(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name)
        VALUES ('theses', 'nokey-' || nextval('source_persons_id_seq'), %s, %s, %s)
        RETURNING id
        """,
        (full_name, last_name, first_name),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_theses_source_authorship(
    cur: Any,
    *,
    source_publication_id: int,
    source_person_id: int,
    author_position: int | None,
    roles: list[str],
    raw_author_name: str,
) -> int:
    """UPSERT d'une `source_authorships` theses.fr. `author_position` NULL pour les non-auteurs."""
    cur.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             author_name_normalized, roles,
             raw_author_name)
        VALUES ('theses', %s, %s, %s, normalize_name_form(%s), %s, %s)
        ON CONFLICT (source_publication_id, source_person_id, author_position) DO UPDATE SET
            roles = EXCLUDED.roles,
            author_name_normalized = EXCLUDED.author_name_normalized,
            raw_author_name = EXCLUDED.raw_author_name
        RETURNING id
        """,
        (
            source_publication_id,
            source_person_id,
            author_position,
            raw_author_name,
            roles,
            raw_author_name,
        ),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def get_theses_publication_id(cur: Any, theses_id: str) -> int | None:
    """Idempotence : retourne le `publication_id` existant pour un document theses.fr."""
    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'theses' AND source_id = %s",
        (theses_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row["publication_id"] if isinstance(row, dict) else row[0]


class PgThesesNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_theses.ThesesNormalizeQueries`."""

    def fetch_thesis_primary_author(self, cur: Any, publication_id: int) -> tuple[str, str] | None:
        return fetch_thesis_primary_author(cur, publication_id)

    def merge_publication_meta(self, cur: Any, publication_id: int, meta_json: Any) -> None:
        merge_publication_meta(cur, publication_id, meta_json)

    def upsert_theses_source_publication(
        self,
        cur: Any,
        *,
        theses_id: str,
        doi: str | None,
        title: str,
        pub_year: int | None,
        doc_type: str,
        publication_id: int | None,
        staging_id: int,
        external_ids: Any,
        journal_id: int | None,
        oa_status: str | None,
        language: str | None,
        container_title: str | None,
        keywords: list[str] | None,
        topics_json: Any,
        source_meta_json: Any,
    ) -> int:
        return upsert_theses_source_publication(
            cur,
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

    def upsert_theses_source_person_by_ppn(
        self,
        cur: Any,
        *,
        ppn: str,
        full_name: str,
        last_name: str,
        first_name: str | None,
    ) -> int:
        return upsert_theses_source_person_by_ppn(
            cur, ppn=ppn, full_name=full_name, last_name=last_name, first_name=first_name
        )

    def find_theses_source_person_by_name(
        self, cur: Any, *, full_name: str, first_name: str | None
    ) -> int | None:
        return find_theses_source_person_by_name(cur, full_name=full_name, first_name=first_name)

    def insert_theses_source_person_new(
        self, cur: Any, *, full_name: str, last_name: str, first_name: str | None
    ) -> int:
        return insert_theses_source_person_new(
            cur, full_name=full_name, last_name=last_name, first_name=first_name
        )

    def upsert_theses_source_authorship(
        self,
        cur: Any,
        *,
        source_publication_id: int,
        source_person_id: int,
        author_position: int | None,
        roles: list[str],
        raw_author_name: str,
    ) -> int:
        return upsert_theses_source_authorship(
            cur,
            source_publication_id=source_publication_id,
            source_person_id=source_person_id,
            author_position=author_position,
            roles=roles,
            raw_author_name=raw_author_name,
        )

    def get_theses_publication_id(self, cur: Any, theses_id: str) -> int | None:
        return get_theses_publication_id(cur, theses_id)

    def count_theses_table(self, cur: Any, table: str) -> int:
        return count_theses_table(cur, table)

    def clear_source_authorships_for_publication(
        self, cur: Any, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(cur, source_publication_id)


def count_theses_table(cur: Any, table: str) -> int:
    """Compte les lignes d'une table avec `source = 'theses'`.

    `table` est une valeur littérale contrôlée par le code appelant (liste blanche).
    """
    if table not in ("source_publications", "source_persons", "source_authorships"):
        raise ValueError(f"Table inattendue : {table!r}")
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE source = 'theses'")
    row = cur.fetchone()
    return row["cnt"] if isinstance(row, dict) else row[0]
