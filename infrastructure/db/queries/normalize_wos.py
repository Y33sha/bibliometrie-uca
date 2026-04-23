"""Query service : SQL du normaliseur Web of Science.

Appelé par `application/pipeline/normalize/normalize_wos.py`. Regroupe les
UPSERT batch (via `cur.executemany`) sur `source_persons`,
`source_structures`, `source_authorships`, `source_authorship_addresses`,
et les lectures/préchargements de caches.
"""

from typing import Any


def upsert_wos_source_publication(
    cur: Any,
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
    biblio: Any,
    keywords: list[str] | None,
    topics: Any,
    urls: list[str] | None,
    external_ids: Any,
) -> int:
    """UPSERT d'un document WoS dans `source_publications`."""
    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id,
             journal_id, oa_status, language, container_title,
             abstract, cited_by_count, biblio, keywords, topics,
             urls, external_ids)
        VALUES ('wos', %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s)
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
        """,
        (
            ut,
            doi,
            title,
            pub_year,
            doc_type,
            publication_id,
            staging_id,
            journal_id,
            oa_status,
            language,
            container_title,
            abstract,
            cited_by_count,
            biblio,
            keywords,
            topics,
            urls,
            external_ids,
        ),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def upsert_wos_source_person(
    cur: Any,
    *,
    daisng_id: str,
    full_name: str,
    last_name: str | None,
    first_name: str | None,
    orcid: str | None,
    source_ids_json: Any,
) -> int:
    """UPSERT d'un `source_persons` WoS (dédup sur daisng_id = source_id)."""
    cur.execute(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name, orcid, source_ids)
        VALUES ('wos', %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
            full_name = EXCLUDED.full_name,
            source_ids = COALESCE(source_persons.source_ids, '{}') ||
                         COALESCE(EXCLUDED.source_ids, '{}')
        RETURNING id
        """,
        (daisng_id, full_name, last_name, first_name, orcid, source_ids_json),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def upsert_wos_source_persons_batch(
    cur: Any, values: list[tuple[Any, ...]]
) -> list[tuple[int, str]]:
    """Batch UPSERT de `source_persons` WoS. Retourne `[(id, source_id), ...]`."""
    if not values:
        return []
    cur.executemany(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name, orcid, source_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
            full_name = EXCLUDED.full_name,
            source_ids = COALESCE(source_persons.source_ids, '{}'::jsonb) ||
                         COALESCE(EXCLUDED.source_ids, '{}'::jsonb)
        RETURNING id, source_id
        """,
        values,
    )
    return list(cur.fetchall())


def upsert_wos_source_structure(cur: Any, *, name: str, ror_id: str | None) -> int:
    """UPSERT d'une `source_structures` WoS (source_id = name)."""
    cur.execute(
        """
        INSERT INTO source_structures (source, source_id, name, ror_id)
        VALUES ('wos', %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            ror_id = COALESCE(source_structures.ror_id, EXCLUDED.ror_id)
        RETURNING id
        """,
        (name, name, ror_id),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def upsert_addresses_batch(cur: Any, values: list[tuple[str, str]]) -> None:
    """INSERT INTO addresses ON CONFLICT DO NOTHING pour un batch `(raw_text, normalized_text)`."""
    if not values:
        return
    cur.executemany(
        """
        INSERT INTO addresses (raw_text, normalized_text)
        VALUES (%s, %s)
        ON CONFLICT (md5(raw_text)) DO NOTHING
        """,
        values,
    )


def fetch_address_ids_by_raw_text(cur: Any, raw_texts: list[str]) -> dict[str, int]:
    """Retourne `{raw_text: id}` pour un lot d'adresses."""
    cur.execute(
        "SELECT raw_text, id FROM addresses WHERE raw_text = ANY(%s)",
        (raw_texts,),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def upsert_wos_source_authorships_batch(cur: Any, values: list[tuple[Any, ...]]) -> None:
    """Batch UPSERT de `source_authorships` WoS."""
    if not values:
        return
    cur.executemany(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             is_corresponding, author_name_normalized,
             source_struct_ids, roles, raw_author_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_publication_id, source_person_id) DO UPDATE SET
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
            raw_author_name = EXCLUDED.raw_author_name
        """,
        values,
    )


def fetch_source_authorship_ids(
    cur: Any, *, source_publication_id: int, source_person_ids: list[int]
) -> dict[int, int]:
    """Retourne `{source_person_id: source_authorship_id}` pour un document donné."""
    cur.execute(
        """
        SELECT source_person_id, id FROM source_authorships
        WHERE source_publication_id = %s AND source_person_id = ANY(%s)
        """,
        (source_publication_id, source_person_ids),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def insert_source_authorship_addresses_batch(cur: Any, values: list[tuple[int, int]]) -> None:
    """Batch INSERT de liens `source_authorship_addresses`."""
    if not values:
        return
    cur.executemany(
        """
        INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
        VALUES (%s, %s)
        ON CONFLICT (source_authorship_id, address_id) DO NOTHING
        """,
        values,
    )


def get_wos_publication_id(cur: Any, ut: str) -> int | None:
    """Idempotence : retourne le `publication_id` déjà associé au document WoS."""
    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'wos' AND source_id = %s",
        (ut,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    pid = row[0] if isinstance(row, tuple) else row["publication_id"]
    return pid if pid else None


def fetch_wos_source_structures(cur: Any) -> list[tuple[str, int]]:
    """Charge `(source_id, id)` des `source_structures` WoS (préchargement cache)."""
    cur.execute("SELECT source_id, id FROM source_structures WHERE source = 'wos'")
    return [(r[0], r[1]) for r in cur.fetchall()]


def fetch_wos_source_persons_with_daisng(cur: Any) -> list[tuple[str, int]]:
    """Charge `(source_id, id)` des `source_persons` WoS avec un daisng_id (préchargement cache).

    Exclut les `source_id LIKE 'wos-%'` (sans daisng_id — pas dans le cache).
    """
    cur.execute(
        "SELECT source_id, id FROM source_persons WHERE source = 'wos' "
        "AND source_id NOT LIKE 'wos-%%'"
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def delete_wos_duplicate_authorships(cur: Any) -> int:
    """Supprime les `source_authorships` WoS en doublon de position.

    WoS renvoie parfois 2 entrées `name` au même `seq_no` pour les publis
    consortium (ATLAS/CERN) : typiquement 1 avec un `daisng_id` renseigné
    et 1 héritée d'un ancien code sans `daisng_id` (source_id synthétique
    `wos-XXXX`). Le parseur actuel n'y crée plus ce cas (cf. filter
    `if not daisng_id: continue`), mais les rows historiques subsistent.

    Heuristique : on garde la row dont le ``source_persons`` a un
    ``daisng_id`` (``source_id NOT LIKE 'wos-%%'``). À égalité
    (deux daisng_id, auteur désambiguïsé deux fois côté WoS), on garde
    la row la plus récente (``id`` max). Retourne le nombre de lignes
    supprimées.
    """
    cur.execute("""
        WITH ranked AS (
            SELECT sa.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY sa.source_publication_id, sa.author_position
                       ORDER BY
                           (sp.source_id LIKE 'wos-%%') ASC,
                           sa.id DESC
                   ) AS rn
            FROM source_authorships sa
            JOIN source_persons sp ON sp.id = sa.source_person_id
            WHERE sa.source = 'wos' AND sa.author_position IS NOT NULL
        )
        DELETE FROM source_authorships
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
    """)
    return cur.rowcount


def delete_wos_orphan_legacy_source_persons(cur: Any) -> int:
    """Supprime les `source_persons` WoS legacy (``source_id`` ``wos-XXXX``,
    sans ``daisng_id``) devenus orphelins après cleanup des doublons.

    Ces rows provenaient d'un ancien code qui créait des identifiants
    synthétiques quand l'API WoS ne renvoyait pas de daisng_id ; le code
    actuel skip ce cas. Retourne le nombre de lignes supprimées.
    """
    cur.execute("""
        DELETE FROM source_persons
        WHERE source = 'wos'
          AND source_id LIKE 'wos-%%'
          AND NOT EXISTS (
              SELECT 1 FROM source_authorships
              WHERE source_person_id = source_persons.id
          )
    """)
    return cur.rowcount


class PgWosNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_wos.WosNormalizeQueries`."""

    def upsert_wos_source_publication(self, cur: Any, **kwargs: Any) -> int:
        return upsert_wos_source_publication(cur, **kwargs)

    def upsert_wos_source_person(self, cur: Any, **kwargs: Any) -> int:
        return upsert_wos_source_person(cur, **kwargs)

    def upsert_wos_source_persons_batch(
        self, cur: Any, values: list[tuple[Any, ...]]
    ) -> list[tuple[int, str]]:
        return upsert_wos_source_persons_batch(cur, values)

    def upsert_wos_source_structure(self, cur: Any, *, name: str, ror_id: str | None) -> int:
        return upsert_wos_source_structure(cur, name=name, ror_id=ror_id)

    def upsert_addresses_batch(self, cur: Any, values: list[tuple[str, str]]) -> None:
        upsert_addresses_batch(cur, values)

    def fetch_address_ids_by_raw_text(self, cur: Any, raw_texts: list[str]) -> dict[str, int]:
        return fetch_address_ids_by_raw_text(cur, raw_texts)

    def upsert_wos_source_authorships_batch(self, cur: Any, values: list[tuple[Any, ...]]) -> None:
        upsert_wos_source_authorships_batch(cur, values)

    def fetch_source_authorship_ids(
        self, cur: Any, *, source_publication_id: int, source_person_ids: list[int]
    ) -> dict[int, int]:
        return fetch_source_authorship_ids(
            cur,
            source_publication_id=source_publication_id,
            source_person_ids=source_person_ids,
        )

    def insert_source_authorship_addresses_batch(
        self, cur: Any, values: list[tuple[int, int]]
    ) -> None:
        insert_source_authorship_addresses_batch(cur, values)

    def get_wos_publication_id(self, cur: Any, ut: str) -> int | None:
        return get_wos_publication_id(cur, ut)

    def fetch_wos_source_structures(self, cur: Any) -> list[tuple[str, int]]:
        return fetch_wos_source_structures(cur)

    def fetch_wos_source_persons_with_daisng(self, cur: Any) -> list[tuple[str, int]]:
        return fetch_wos_source_persons_with_daisng(cur)

    def delete_wos_duplicate_authorships(self, cur: Any) -> int:
        return delete_wos_duplicate_authorships(cur)

    def delete_wos_orphan_legacy_source_persons(self, cur: Any) -> int:
        return delete_wos_orphan_legacy_source_persons(cur)
