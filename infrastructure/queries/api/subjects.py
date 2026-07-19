"""Query service : lectures des sujets servies par les routes `/api/subjects/*`.

Les écritures du référentiel appartiennent à la phase d'ingestion, dont l'adaptateur vit dans `infrastructure.queries.pipeline.subjects`.
"""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.subjects_queries import (
    SubjectListItem,
    SubjectNeighborOut,
    SubjectsQueries,
)


def _search_clause(q: str | None, min_usage_count: int) -> tuple[str, dict[str, Any]]:
    """Clause de recherche de l'annuaire des sujets, avec ses paramètres.

    La liste et son total la partagent : un critère ajouté d'un seul côté fausserait la pagination.
    """
    where = "usage_count >= :min_count"
    binds: dict[str, Any] = {"min_count": min_usage_count}
    if q:
        where += " AND unaccent(label) ILIKE unaccent(:q)"
        binds["q"] = f"%{q}%"
    return where, binds


class PgSubjectsQueries(SubjectsQueries):
    """Adapter SA pour `application.ports.api.subjects_queries.SubjectsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_subjects(
        self, *, q: str | None, limit: int, offset: int, min_usage_count: int
    ) -> list[SubjectListItem]:
        where, binds = _search_clause(q, min_usage_count)
        rows = self._conn.execute(
            text(f"""
                SELECT id, label, language, usage_count
                FROM subjects
                WHERE {where}
                ORDER BY usage_count DESC, lower(label)
                LIMIT :lim OFFSET :off
            """),
            {**binds, "lim": limit, "off": offset},
        ).all()
        return [
            SubjectListItem(
                id=r.id,
                label=r.label,
                language=r.language,
                usage_count=r.usage_count,
            )
            for r in rows
        ]

    def count_subjects(self, *, q: str | None, min_usage_count: int) -> int:
        where, binds = _search_clause(q, min_usage_count)
        row = self._conn.execute(
            text(f"SELECT COUNT(*) AS n FROM subjects WHERE {where}"),
            binds,
        ).one()
        return row.n

    def get_subject(self, subject_id: int) -> SubjectListItem | None:
        row = self._conn.execute(
            text("""
                SELECT id, label, language, usage_count
                FROM subjects
                WHERE id = :id
            """),
            {"id": subject_id},
        ).one_or_none()
        if row is None:
            return None
        return SubjectListItem(
            id=row.id,
            label=row.label,
            language=row.language,
            usage_count=row.usage_count,
        )

    def get_subject_neighbors(
        self, subject_id: int, *, limit: int, min_cooccurrence_count: int
    ) -> list[SubjectNeighborOut]:
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.label, s.usage_count,
                       c.n AS cooccurrence_count
                FROM (
                    SELECT subject_b_id AS other, count AS n
                    FROM subject_cooccurrences WHERE subject_a_id = :sid
                    UNION ALL
                    SELECT subject_a_id AS other, count AS n
                    FROM subject_cooccurrences WHERE subject_b_id = :sid
                ) c
                JOIN subjects s ON s.id = c.other
                WHERE c.n >= :min_count
                ORDER BY c.n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"sid": subject_id, "min_count": min_cooccurrence_count, "lim": limit},
        ).all()
        return [
            SubjectNeighborOut(
                id=r.id,
                label=r.label,
                usage_count=r.usage_count,
                cooccurrence_count=r.cooccurrence_count,
            )
            for r in rows
        ]


__all__ = ["PgSubjectsQueries"]
