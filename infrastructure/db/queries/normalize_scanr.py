"""Query service : SQL du normaliseur ScanR.

Appelé par `application/pipeline/normalize/normalize_scanr.py`. Regroupe
les UPSERT sur `source_publications`, `source_persons`, `source_authorships`
et la lecture idempotence.
"""

from typing import Any


def upsert_scanr_source_publication(
    cur: Any,
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
    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, topics, cited_by_count, urls)
        VALUES ('scanr', %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s)
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
        """,
        (
            scanr_id,
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
            abstract,
            keywords,
            topics,
            cited_by_count,
            urls,
        ),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_scanr_source_person_by_idref(
    cur: Any,
    *,
    idref: str,
    full_name: str,
    last_name: str | None,
    first_name: str | None,
    orcid: str | None,
) -> int:
    """UPSERT d'un `source_persons` ScanR dédupliqué sur `idref`."""
    cur.execute(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name, orcid, idref)
        VALUES ('scanr', %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
            full_name = EXCLUDED.full_name,
            idref = COALESCE(source_persons.idref, EXCLUDED.idref)
        RETURNING id
        """,
        (idref, full_name, last_name, first_name, orcid, idref),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def find_scanr_source_person_by_name(
    cur: Any, *, full_name: str, first_name: str | None
) -> int | None:
    """Cherche un `source_persons` ScanR (sans idref) par nom exact."""
    cur.execute(
        """
        SELECT id FROM source_persons
        WHERE source = 'scanr'
          AND source_id LIKE 'scanr-%%'
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


def insert_scanr_source_person_new(
    cur: Any,
    *,
    full_name: str,
    last_name: str | None,
    first_name: str | None,
    orcid: str | None,
) -> int:
    """Crée un nouveau `source_persons` ScanR sans `idref`, avec `source_id` séquentiel."""
    cur.execute("SELECT nextval('source_persons_id_seq')")
    row = cur.fetchone()
    next_id = row["nextval"] if isinstance(row, dict) else row[0]
    source_id = f"scanr-{next_id}"
    cur.execute(
        """
        INSERT INTO source_persons
            (id, source, source_id, full_name, last_name, first_name, orcid)
        VALUES (%s, 'scanr', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (next_id, source_id, full_name, last_name, first_name, orcid),
    )
    inserted = cur.fetchone()
    return inserted["id"] if isinstance(inserted, dict) else inserted[0]


def upsert_scanr_source_authorship(
    cur: Any,
    *,
    source_publication_id: int,
    source_person_id: int,
    author_position: int,
    roles: list[str] | None,
    raw_author_name: str | None,
) -> int:
    """UPSERT d'une `source_authorships` ScanR. Retourne l'id."""
    cur.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position, roles,
             author_name_normalized, raw_author_name)
        VALUES ('scanr', %s, %s, %s, %s, normalize_name_form(%s), %s)
        ON CONFLICT (source_publication_id, source_person_id) DO UPDATE SET
            author_name_normalized = EXCLUDED.author_name_normalized,
            roles = EXCLUDED.roles,
            raw_author_name = EXCLUDED.raw_author_name
        RETURNING id
        """,
        (
            source_publication_id,
            source_person_id,
            author_position,
            roles,
            raw_author_name,
            raw_author_name,
        ),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def get_scanr_publication_id(cur: Any, scanr_id: str) -> int | None:
    """Idempotence : retourne `publication_id` déjà associé au document ScanR."""
    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'scanr' AND source_id = %s",
        (scanr_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row["publication_id"] if isinstance(row, dict) else row[0]
