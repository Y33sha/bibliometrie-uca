"""Query service : SQL du normaliseur OpenAlex.

Appelé par `application/pipeline/normalize/normalize_openalex.py`.
Regroupe les UPSERT sur `source_publications`, `source_persons`,
`source_structures`, `source_authorships`, ainsi que les lectures
d'idempotence et les déduplications Zenodo.
"""

from typing import Any

from infrastructure.db.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


def fetch_publication_id_for_hal_source(cur: Any, hal_id: str) -> int | None:
    """Retourne `publication_id` du document HAL correspondant (pour cross-référence)."""
    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'hal' AND source_id = %s",
        (hal_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    pid = row["publication_id"] if isinstance(row, dict) else row[0]
    return pid if pid else None


def upsert_openalex_source_publication(
    cur: Any,
    *,
    openalex_id: str,
    doi: str | None,
    title: str,
    pub_year: int | None,
    doc_type: str | None,
    publication_id: int | None,
    staging_id: int,
    external_ids: Any,
    urls: list[str] | None,
    cited_by_count: int | None,
    journal_id: int | None,
    oa_status: str | None,
    language: str | None,
    container_title: str | None,
    is_retracted: bool | None,
    biblio: Any,
    abstract: str | None,
    keywords: list[str] | None,
    topics_json: Any,
) -> int:
    """UPSERT d'un document OpenAlex dans `source_publications`."""
    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids, urls, cited_by_count,
             journal_id, oa_status, language, container_title,
             is_retracted, biblio, abstract, keywords, topics)
        VALUES ('openalex', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            is_retracted = COALESCE(EXCLUDED.is_retracted, source_publications.is_retracted),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics)
        RETURNING id
        """,
        (
            openalex_id,
            doi,
            title,
            pub_year,
            doc_type,
            publication_id,
            staging_id,
            external_ids,
            urls,
            cited_by_count,
            journal_id,
            oa_status,
            language,
            container_title,
            is_retracted,
            biblio,
            abstract,
            keywords,
            topics_json,
        ),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def find_openalex_source_structure(cur: Any, openalex_id: str) -> int | None:
    """Cherche une `source_structures` OpenAlex par `source_id`."""
    cur.execute(
        "SELECT id FROM source_structures WHERE source = 'openalex' AND source_id = %s",
        (openalex_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_openalex_source_structure(
    cur: Any,
    *,
    openalex_id: str,
    name: str,
    ror_id: str | None,
    country: str | None,
    source_data: Any,
) -> int:
    """UPSERT d'une `source_structures` OpenAlex."""
    cur.execute(
        """
        INSERT INTO source_structures
            (source, source_id, name, ror_id, country, source_data)
        VALUES ('openalex', %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            name = COALESCE(NULLIF(source_structures.name, ''), EXCLUDED.name),
            ror_id = COALESCE(source_structures.ror_id, EXCLUDED.ror_id),
            source_data = COALESCE(source_structures.source_data, '{}') ||
                          COALESCE(EXCLUDED.source_data, '{}')
        RETURNING id
        """,
        (openalex_id, name, ror_id, country, source_data),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_openalex_source_authorship(
    cur: Any,
    *,
    source_publication_id: int,
    source_person_id: int | None,
    author_position: int,
    source_struct_ids: list[int] | None,
    raw_author_name: str | None,
    is_corresponding: bool,
    identifiers: Any,
) -> int:
    """UPSERT d'une `source_authorships` OpenAlex.

    `source_person_id` est NULL : depuis le chantier source_persons,
    OpenAlex n'écrit plus dans `source_persons` (entités auteurs
    algorithmiques non fiables). Les identifiants normalisés (orcid)
    vivent sur `identifiers`.
    """
    cur.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             source_struct_ids,
             author_name_normalized, is_corresponding, raw_author_name, identifiers)
        VALUES ('openalex', %s, %s, %s, %s, normalize_name_form(%s), %s, %s, %s)
        ON CONFLICT (source_publication_id, source_person_id, author_position) DO UPDATE SET
            author_name_normalized = COALESCE(
                EXCLUDED.author_name_normalized,
                source_authorships.author_name_normalized
            ),
            is_corresponding = EXCLUDED.is_corresponding,
            raw_author_name = EXCLUDED.raw_author_name,
            identifiers = EXCLUDED.identifiers
        RETURNING id
        """,
        (
            source_publication_id,
            source_person_id,
            author_position,
            source_struct_ids,
            raw_author_name,
            is_corresponding,
            raw_author_name,
            identifiers,
        ),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def staging_has_openalex_doi(cur: Any, doi: str) -> bool:
    """Vrai si le DOI est déjà présent dans `staging` pour `source='openalex'`."""
    cur.execute(
        "SELECT id FROM staging WHERE source = 'openalex' AND lower(doi) = lower(%s)",
        (doi,),
    )
    return cur.fetchone() is not None


def get_openalex_publication_id(cur: Any, openalex_id: str) -> int | None:
    """Idempotence : retourne `publication_id` déjà associé au document OpenAlex."""
    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'openalex' AND source_id = %s",
        (openalex_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    pid = row["publication_id"] if isinstance(row, dict) else row[0]
    return pid if pid else None


class PgOpenalexNormalizeQueries:
    """Adapter PostgreSQL pour `application.ports.normalize_openalex.OpenalexNormalizeQueries`."""

    def fetch_publication_id_for_hal_source(self, cur: Any, hal_id: str) -> int | None:
        return fetch_publication_id_for_hal_source(cur, hal_id)

    def upsert_openalex_source_publication(self, cur: Any, **kwargs: Any) -> int:
        return upsert_openalex_source_publication(cur, **kwargs)

    def find_openalex_source_structure(self, cur: Any, openalex_id: str) -> int | None:
        return find_openalex_source_structure(cur, openalex_id)

    def upsert_openalex_source_structure(self, cur: Any, **kwargs: Any) -> int:
        return upsert_openalex_source_structure(cur, **kwargs)

    def upsert_openalex_source_authorship(self, cur: Any, **kwargs: Any) -> int:
        return upsert_openalex_source_authorship(cur, **kwargs)

    def staging_has_openalex_doi(self, cur: Any, doi: str) -> bool:
        return staging_has_openalex_doi(cur, doi)

    def get_openalex_publication_id(self, cur: Any, openalex_id: str) -> int | None:
        return get_openalex_publication_id(cur, openalex_id)

    def count_openalex_table(self, cur: Any, table: str) -> int:
        return count_openalex_table(cur, table)

    def clear_source_authorships_for_publication(
        self, cur: Any, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(cur, source_publication_id)


def count_openalex_table(cur: Any, table: str) -> int:
    """Compte les lignes d'une table avec `source = 'openalex'` (liste blanche).

    `source_persons` reste accepté pour permettre de tracer les rows
    legacy (cf. `docs/chantiers/2026-04-28_source-persons.md`).
    """
    if table not in ("source_publications", "source_persons", "source_structures"):
        raise ValueError(f"Table inattendue : {table!r}")
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE source = 'openalex'")
    row = cur.fetchone()
    return row["cnt"] if isinstance(row, dict) else row[0]
