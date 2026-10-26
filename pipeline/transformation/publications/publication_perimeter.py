"""Recalcul de `publications.perimeter_evidence`, par la phase `contributions`, après une correction d'adresse et après les décisions de l'administration sur une personne ou sur ses contributions.

Une publication réunit les indices de ses contributions d'auteurs (groupes de contributions sources rattachés à une personne non exclue) : direction de thèse, jury, édition ou traduction comptent pour la personne, pas pour le périmètre. Une thèse soutenue dans un établissement du périmètre reçoit en plus l'indice `thesis_institution`.
"""

from sqlalchemy import Connection, text

from domain.source_records.source_extras import SourceExtra
from domain.structures.perimeter_evidence import PerimeterEvidence
from infrastructure.read_models.perimeters import get_persons_structure_ids_list
from infrastructure.sql_fragments import NO_PERIMETER_EVIDENCE, has_author_role, source_extra


def _refresh_sql(scope: str) -> str:
    """Indices de chaque publication de `scope`. `scope` : condition sur l'id de publication. `:thesis_ppns` : PPN des établissements de soutenance du périmètre."""
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
                SELECT sr.publication_id, '{PerimeterEvidence.THESIS_INSTITUTION}'::perimeter_evidence
                FROM source_records sr
                WHERE sr.publication_id {scope}
                  AND sr.source = 'theses'
                  AND {source_extra(SourceExtra.ETABLISSEMENT_PPN)} = ANY(:thesis_ppns)
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


def _thesis_ppns(conn: Connection) -> list[str]:
    """PPN des établissements de soutenance du périmètre des personnes (`api_ids.theses`)."""
    return list(
        conn.execute(
            text("""
                SELECT DISTINCT t.value
                FROM structures s
                CROSS JOIN LATERAL jsonb_array_elements_text(s.api_ids -> 'theses') t(value)
                WHERE s.id = ANY(:ids) AND s.api_ids ? 'theses'
            """),
            {"ids": get_persons_structure_ids_list(conn)},
        ).scalars()
    )


def refresh_publications_perimeter_evidence(
    conn: Connection, person_id: int | None = None, publication_ids: list[int] | None = None
) -> int:
    """Matérialise `publications.perimeter_evidence`, pour toutes les publications, celles de la personne `person_id`, ou `publication_ids`. Rend le nombre de publications changées. Idempotent."""
    params: dict[str, object] = {"thesis_ppns": _thesis_ppns(conn)}
    if person_id is not None:
        return conn.execute(_OF_PERSON, {**params, "pid": person_id}).rowcount
    if publication_ids is not None:
        return conn.execute(
            _OF_PUBLICATIONS, {**params, "publication_ids": publication_ids}
        ).rowcount
    return conn.execute(_ALL, params).rowcount


class PublicationPerimeterRecompute:
    """Recalcul ciblé de `publications.perimeter_evidence`, exposé à l'API par `pipeline/public.py`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def refresh_publications_of_person(self, person_id: int) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications de la personne. Rend le nombre de publications changées."""
        return refresh_publications_perimeter_evidence(self._conn, person_id)

    def refresh_publications(self, publication_ids: list[int]) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications `publication_ids`. Rend le nombre de publications changées."""
        if not publication_ids:
            return 0
        return refresh_publications_perimeter_evidence(self._conn, publication_ids=publication_ids)
