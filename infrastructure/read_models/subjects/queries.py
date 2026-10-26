"""Query service : lectures des sujets servies par les routes `/api/subjects/*`.

Les écritures du référentiel appartiennent à la phase `subjects` (`pipeline/transformation/publications/subjects/subjects_queries.py`).
"""

from sqlalchemy import Connection, Row, text

from infrastructure.read_models.subjects.models import (
    SubjectDetailResponse,
    SubjectListItem,
    SubjectListResponse,
    SubjectNeighborLink,
    SubjectNeighborOut,
)


def _search_clause(search: str | None, min_usage_count: int) -> tuple[str, dict[str, object]]:
    """Clause de recherche de l'annuaire des sujets, avec ses paramètres.

    La liste et son total la partagent : un critère ajouté d'un seul côté fausserait la pagination.
    """
    where = "usage_count >= :min_count"
    binds: dict[str, object] = {"min_count": min_usage_count}
    if search:
        where += " AND unaccent(label) ILIKE unaccent(:search)"
        binds["search"] = f"%{search}%"
    return where, binds


def _subject_list_item(row: Row[tuple[object, ...]]) -> SubjectListItem:
    return SubjectListItem(
        id=row.id, label=row.label, language=row.language, usage_count=row.usage_count
    )


class SubjectsQueries:
    """Lectures sur les sujets."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_subjects(
        self, *, search: str | None, page: int, per_page: int, min_usage_count: int
    ) -> SubjectListResponse:
        where, binds = _search_clause(search, min_usage_count)
        rows = self._conn.execute(
            text(f"""
                SELECT id, label, language, usage_count
                FROM subjects
                WHERE {where}
                ORDER BY usage_count DESC, lower(label)
                LIMIT :lim OFFSET :off
            """),
            {**binds, "lim": per_page, "off": (page - 1) * per_page},
        ).all()
        items = [_subject_list_item(r) for r in rows]
        total = (
            self._conn.execute(
                text(f"SELECT COUNT(*) AS n FROM subjects WHERE {where}"),
                binds,
            )
            .one()
            .n
        )
        return SubjectListResponse(items=items, total=total, page=page, per_page=per_page)

    def get_subject_detail(
        self, subject_id: int, *, neighbors_limit: int, min_cooccurrence_count: int
    ) -> SubjectDetailResponse | None:
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
        subject = _subject_list_item(row)
        neighbor_rows = self._conn.execute(
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
            {"sid": subject_id, "min_count": min_cooccurrence_count, "lim": neighbors_limit},
        ).all()
        neighbors = [
            SubjectNeighborOut(
                id=r.id,
                label=r.label,
                usage_count=r.usage_count,
                cooccurrence_count=r.cooccurrence_count,
            )
            for r in neighbor_rows
        ]
        link_rows = self._conn.execute(
            text("""
                SELECT subject_a_id, subject_b_id, count AS cooccurrence_count
                FROM subject_cooccurrences
                WHERE subject_a_id = ANY(:ids) AND subject_b_id = ANY(:ids) AND count >= :min_count
            """),
            {"ids": [n.id for n in neighbors], "min_count": min_cooccurrence_count},
        ).all()
        neighbor_links = [
            SubjectNeighborLink(
                subject_a_id=r.subject_a_id,
                subject_b_id=r.subject_b_id,
                cooccurrence_count=r.cooccurrence_count,
            )
            for r in link_rows
        ]
        return SubjectDetailResponse(
            subject=subject, neighbors=neighbors, neighbor_links=neighbor_links
        )


__all__ = ["SubjectsQueries"]
