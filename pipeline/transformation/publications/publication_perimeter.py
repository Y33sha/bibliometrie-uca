"""Recalcul de `publications.perimeter_evidence`, par la phase `finalize`, après une correction d'adresse, et après une décision de l'administration sur une personne ou sur ses contributions.

Une publication réunit les indices de ses contributions d'auteurs, rattachées à une personne non exclue. Direction de thèse, jury, édition ou traduction comptent pour la personne, et restent hors du périmètre. Elle reçoit en plus les indices d'appartenance au périmètre liés au document (`DOCUMENT_EVIDENCE`), portés par ses contributions sources de tout rôle.
"""

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import (
    DOCUMENT_EVIDENCE_SQL,
    NO_PERIMETER_EVIDENCE,
    has_author_role,
)


def _refresh_sql(scope: str) -> str:
    """Renvoie la requête de recalcul des indices de chaque publication de `scope`.

    Args:
        scope: condition sur l'id de publication.
    """
    return f"""
        WITH computed AS (
            SELECT id, array_agg(DISTINCT e ORDER BY e) AS evidence
            FROM (
                SELECT a.publication_id AS id, e
                FROM contributions a
                JOIN persons pe ON pe.id = a.person_id AND pe.exclusion IS NULL
                CROSS JOIN LATERAL unnest(a.perimeter_evidence) e
                WHERE a.publication_id {scope} AND {has_author_role("a")}
                UNION
                SELECT sr.publication_id, e
                FROM source_records sr
                JOIN source_contributions sc ON sc.source_record_id = sr.id
                CROSS JOIN LATERAL unnest(sc.perimeter_evidence) e
                WHERE sr.publication_id {scope} AND e = ANY({DOCUMENT_EVIDENCE_SQL})
            ) by_publication
            GROUP BY id
        ), target AS (
            SELECT p.id, coalesce(c.evidence, {NO_PERIMETER_EVIDENCE}) AS evidence
            FROM publications p
            LEFT JOIN computed c ON c.id = p.id
            WHERE p.id {scope}
        )
        UPDATE publications p
        SET perimeter_evidence = t.evidence
        FROM target t
        WHERE p.id = t.id AND p.perimeter_evidence IS DISTINCT FROM t.evidence
    """


_ALL = text(_refresh_sql("IS NOT NULL"))
_OF_PERSON = text(
    _refresh_sql("IN (SELECT publication_id FROM contributions WHERE person_id = :pid)")
)
_OF_PUBLICATIONS = text(_refresh_sql("= ANY(:publication_ids)"))


def refresh_publications_perimeter_evidence(
    conn: Connection, person_id: int | None = None, publication_ids: list[int] | None = None
) -> int:
    """Matérialise `publications.perimeter_evidence`, pour toutes les publications, celles de la personne `person_id`, ou `publication_ids`. Renvoie le nombre de publications changées. Idempotent."""
    if person_id is not None:
        return conn.execute(_OF_PERSON, {"pid": person_id}).rowcount
    if publication_ids is not None:
        return conn.execute(_OF_PUBLICATIONS, {"publication_ids": publication_ids}).rowcount
    return conn.execute(_ALL).rowcount


class PublicationPerimeterRecompute:
    """Recalcul ciblé de `publications.perimeter_evidence`, exposé à l'API par `pipeline/public.py`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def refresh_publications_of_person(self, person_id: int) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications de la personne. Renvoie le nombre de publications changées."""
        return refresh_publications_perimeter_evidence(self._conn, person_id)

    def refresh_publications(self, publication_ids: list[int]) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications `publication_ids`. Renvoie le nombre de publications changées."""
        if not publication_ids:
            return 0
        return refresh_publications_perimeter_evidence(self._conn, publication_ids=publication_ids)
