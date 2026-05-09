"""Query services pour /api/admin/duplicates/*.

Implémente le port `application.ports.publication_duplicates_queries.
PublicationDuplicatesQueries` via `PgPublicationDuplicatesQueries`
(duck typing — pas d'import depuis `application/`).
"""

from typing import Any

from sqlalchemy import Connection, text

# `:min_title_len` apparaît une seule fois dans la sous-requête SELECT
# qui est utilisée 2× : une fois pour COUNT, une fois pour LIMIT/OFFSET.
# SA réutilise le même bind dans les deux compositions.
_PUB_CANDIDATE_WHERE = """
    FROM publications p1
    JOIN publications p2
      ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
    WHERE LENGTH(p1.title_normalized) > :min_title_len
      AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL AND LOWER(p1.doi) <> LOWER(p2.doi)
               AND NOT (LOWER(p1.doi) LIKE '10.5281/zenodo.%' AND LOWER(p2.doi) LIKE '10.5281/zenodo.%'))
      AND NOT (
          (p1.doc_type IN ('article', 'review') AND p2.doc_type = 'conference_paper')
          OR (p2.doc_type IN ('article', 'review') AND p1.doc_type = 'conference_paper'))
      AND NOT (EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p1.id AND source = 'hal')
               AND EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p2.id AND source = 'hal'))
      AND NOT (EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p1.id AND source = 'openalex')
               AND EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p2.id AND source = 'openalex'))
      AND NOT (EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p1.id AND source = 'wos')
               AND EXISTS (SELECT 1 FROM source_publications WHERE publication_id = p2.id AND source = 'wos'))
      AND NOT EXISTS (
          SELECT 1 FROM distinct_publications dp
          WHERE dp.pub_id_a = LEAST(p1.id, p2.id) AND dp.pub_id_b = GREATEST(p1.id, p2.id))
"""


class PgPublicationDuplicatesQueries:
    """Adapter SA pour `PublicationDuplicatesQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def _get_pub_detail(self, pub_id: int) -> dict[str, Any] | None:
        pub_row = self._conn.execute(
            text("""
                SELECT p.id, p.title, p.title_normalized, p.doi, p.pub_year,
                       p.doc_type::text AS doc_type, p.container_title,
                       p.oa_status::text AS oa_status,
                       p.language, p.journal_id,
                       j.title AS journal_title, j.issn, j.eissn
                FROM publications p
                LEFT JOIN journals j ON j.id = p.journal_id
                WHERE p.id = :pid
            """),
            {"pid": pub_id},
        ).one_or_none()
        if not pub_row:
            return None

        src_rows = self._conn.execute(
            text("SELECT source, source_id FROM source_publications WHERE publication_id = :pid"),
            {"pid": pub_id},
        ).all()
        sources = [{"source": r.source, "source_id": r.source_id} for r in src_rows]

        auth_rows = self._conn.execute(
            text("""
                SELECT a.author_position, a.in_perimeter, a.person_id,
                       COALESCE(p2.last_name) AS last_name,
                       COALESCE(p2.first_name) AS first_name,
                       COALESCE(p2.last_name || ' ' || p2.first_name,
                                sa_hal.raw_author_name, sa_oa.raw_author_name,
                                sa_wos.raw_author_name) AS full_name
                FROM authorships a
                LEFT JOIN persons p2 ON p2.id = a.person_id
                LEFT JOIN source_authorships sa_hal
                       ON sa_hal.authorship_id = a.id AND sa_hal.source = 'hal'
                LEFT JOIN source_authorships sa_oa
                       ON sa_oa.authorship_id = a.id AND sa_oa.source = 'openalex'
                LEFT JOIN source_authorships sa_wos
                       ON sa_wos.authorship_id = a.id AND sa_wos.source = 'wos'
                WHERE a.publication_id = :pid AND NOT a.excluded
                ORDER BY a.author_position NULLS LAST
            """),
            {"pid": pub_id},
        ).all()
        authors = [dict(r._mapping) for r in auth_rows]

        return {
            "id": pub_row.id,
            "title": pub_row.title,
            "title_normalized": pub_row.title_normalized,
            "doi": pub_row.doi,
            "pub_year": pub_row.pub_year,
            "doc_type": pub_row.doc_type,
            "container_title": pub_row.container_title,
            "oa_status": pub_row.oa_status,
            "language": pub_row.language,
            "journal": {
                "id": pub_row.journal_id,
                "title": pub_row.journal_title,
                "issn": pub_row.issn,
                "eissn": pub_row.eissn,
            }
            if pub_row.journal_id
            else None,
            "sources": sources,
            "authors": authors,
        }

    def next_pub_duplicate(self, *, min_title_len: int, offset: int) -> dict[str, Any]:
        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM (SELECT p1.id {_PUB_CANDIDATE_WHERE}) sub"),
            {"min_title_len": min_title_len},
        ).one()
        total = total_row.total

        pair_row = self._conn.execute(
            text(
                f"SELECT p1.id AS id_a, p2.id AS id_b {_PUB_CANDIDATE_WHERE} "
                f"LIMIT 1 OFFSET :pg_offset"
            ),
            {"min_title_len": min_title_len, "pg_offset": offset},
        ).one_or_none()
        if not pair_row:
            return {"total": total, "offset": offset, "pair": None}

        return {
            "total": total,
            "offset": offset,
            "pair": {
                "pub_a": self._get_pub_detail(pair_row.id_a),
                "pub_b": self._get_pub_detail(pair_row.id_b),
            },
        }

    def get_publications_basic(self, pub_ids: list[int]) -> dict[int, Any]:
        result = self._conn.execute(
            text(
                "SELECT id, doi, journal_id, oa_status::text AS oa_status, "
                "language, container_title "
                "FROM publications WHERE id = ANY(:ids)"
            ),
            {"ids": list(pub_ids)},
        )
        return {row.id: dict(row._mapping) for row in result}
