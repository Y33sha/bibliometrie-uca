"""Recalcul de `publications.perimeter_evidence` depuis les authorships, par la phase `authorships`, après l'exclusion d'une personne et après une correction d'adresse."""

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import NO_PERIMETER_EVIDENCE


def _refresh_sql(scope: str) -> str:
    """Indices de chaque publication de `scope` : union des indices de ses authorships de personnes non exclues. `scope` : condition sur l'id de publication."""
    return f"""
        WITH computed AS (
            SELECT a.publication_id AS id, array_agg(DISTINCT e ORDER BY e) AS evidence
            FROM authorships a
            JOIN persons pe ON pe.id = a.person_id AND pe.exclusion IS NULL
            CROSS JOIN LATERAL unnest(a.perimeter_evidence) e
            WHERE a.publication_id {scope}
            GROUP BY a.publication_id
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
    _refresh_sql("IN (SELECT publication_id FROM authorships WHERE person_id = :pid)")
)
_OF_PUBLICATIONS = text(_refresh_sql("= ANY(:publication_ids)"))


def refresh_publications_perimeter_evidence(
    conn: Connection, person_id: int | None = None, publication_ids: list[int] | None = None
) -> int:
    """Matérialise `publications.perimeter_evidence`, pour toutes les publications, celles de la personne `person_id`, ou `publication_ids`. Rend le nombre de publications changées. Idempotent."""
    if person_id is not None:
        return conn.execute(_OF_PERSON, {"pid": person_id}).rowcount
    if publication_ids is not None:
        return conn.execute(_OF_PUBLICATIONS, {"publication_ids": publication_ids}).rowcount
    return conn.execute(_ALL).rowcount


class PublicationPerimeterRecompute:
    """Recalcul ciblé de `publications.perimeter_evidence`, exposé à l'API par `pipeline/public.py`."""

    def refresh_publications_of_person(self, conn: Connection, person_id: int) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications de la personne. Rend le nombre de publications changées."""
        return refresh_publications_perimeter_evidence(conn, person_id)
