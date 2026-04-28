"""Query service : SQL du normaliseur CrossRef.

Appelé par ``application/pipeline/normalize/normalize_crossref.py``.
Regroupe les UPSERT sur ``source_publications``, ``source_persons``,
``source_authorships`` et la lecture d'idempotence.

Particularité CrossRef : pas d'identifiant stable côté auteur. On
synthétise un ``source_id = "<DOI>:<position>"`` à chaque insertion,
chaque authorship générant un ``source_persons`` qui lui est propre.
La déduplication vers les ``persons`` canoniques est faite plus tard
par le pipeline ``personnes`` (source-agnostique).
"""

from typing import Any

from infrastructure.db.queries.source_authorships import (
    clear_source_authorships_for_publication,
)


def upsert_crossref_source_publication(
    cur: Any,
    *,
    doi: str,
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
    cited_by_count: int | None,
    biblio: Any,
    meta: Any,
) -> int:
    """UPSERT d'une publication CrossRef dans ``source_publications``. Retourne l'id."""
    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, cited_by_count, biblio, meta)
        VALUES ('crossref', %s, %s, %s, %s, %s, %s, %s, %s,
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
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            meta = COALESCE(EXCLUDED.meta, source_publications.meta)
        RETURNING id
        """,
        (
            doi,
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
            cited_by_count,
            biblio,
            meta,
        ),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_crossref_source_authorship(
    cur: Any,
    *,
    source_publication_id: int,
    author_position: int,
    raw_author_name: str | None,
    source_data: Any,
    identifiers: Any,
) -> int:
    """UPSERT d'une ``source_authorships`` CrossRef. Retourne l'id.

    `source_person_id` est NULL : depuis le chantier source_persons,
    CrossRef n'écrit plus dans `source_persons` (les entités auteurs
    CrossRef étaient des `<DOI>:<position>` synthétiques 1:1 avec
    l'authorship — sans bénéfice). L'ORCID, seul identifiant exploitable,
    vit sur `identifiers`.
    """
    cur.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             author_name_normalized, raw_author_name, source_data, identifiers)
        VALUES ('crossref', %s, NULL, %s, normalize_name_form(%s), %s, %s, %s)
        ON CONFLICT (source_publication_id, source_person_id, author_position) DO UPDATE SET
            author_name_normalized = EXCLUDED.author_name_normalized,
            raw_author_name = EXCLUDED.raw_author_name,
            source_data = EXCLUDED.source_data,
            identifiers = EXCLUDED.identifiers
        RETURNING id
        """,
        (
            source_publication_id,
            author_position,
            raw_author_name,
            raw_author_name,
            source_data,
            identifiers,
        ),
    )
    row = cur.fetchone()
    return row[0] if isinstance(row, tuple) else row["id"]


def get_crossref_publication_id(cur: Any, doi: str) -> int | None:
    """Idempotence : retourne ``publication_id`` déjà associé au DOI CrossRef."""
    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'crossref' AND source_id = %s",
        (doi,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row["publication_id"] if isinstance(row, dict) else row[0]


class PgCrossrefNormalizeQueries:
    """Adapter PostgreSQL pour ``application.ports.normalize_crossref.CrossrefNormalizeQueries``."""

    def upsert_crossref_source_publication(
        self,
        cur: Any,
        *,
        doi: str,
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
        cited_by_count: int | None,
        biblio: Any,
        meta: Any,
    ) -> int:
        return upsert_crossref_source_publication(
            cur,
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
            abstract=abstract,
            keywords=keywords,
            cited_by_count=cited_by_count,
            biblio=biblio,
            meta=meta,
        )

    def upsert_crossref_source_authorship(
        self,
        cur: Any,
        *,
        source_publication_id: int,
        author_position: int,
        raw_author_name: str | None,
        source_data: Any,
        identifiers: Any,
    ) -> int:
        return upsert_crossref_source_authorship(
            cur,
            source_publication_id=source_publication_id,
            author_position=author_position,
            raw_author_name=raw_author_name,
            source_data=source_data,
            identifiers=identifiers,
        )

    def get_crossref_publication_id(self, cur: Any, doi: str) -> int | None:
        return get_crossref_publication_id(cur, doi)

    def clear_source_authorships_for_publication(
        self, cur: Any, source_publication_id: int
    ) -> None:
        clear_source_authorships_for_publication(cur, source_publication_id)
