"""Indices de l'entrée des contributions sources dans le périmètre (`source_contributions.perimeter_evidence`), d'après les structures qu'elles atteignent et les identifiants des personnes qui ont une fiche RH.

Le module sert la phase `affiliations` et le recalcul ciblé après une correction d'adresse (`SourceContributionPerimeterRecompute`)."""

from typing import NamedTuple

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.sql_fragments import (
    NO_PERIMETER_EVIDENCE,
    propagate_contribution_attributes_sql,
    source_contribution_perimeter_evidence,
)
from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)


class InPerimeterSyncCounts(NamedTuple):
    """Nombre de contributions sources entrées dans le périmètre et sorties du périmètre lors d'une synchronisation."""

    added: int
    removed: int


def _sync_sql(scoped: bool) -> str:
    """Requête de synchronisation des indices, restreinte à une liste de contributions sources si `scoped` est vrai.

    Seules les contributions sources dont les indices changent sont écrites. Un enregistrement source sans publication dont une contribution source entre dans le périmètre est marqué pour la réconciliation : la phase `publications` le met alors en publication. Les contributions des contributions sources écrites sont marquées pour la recomposition de leurs attributs.
    """
    marked = enqueue_sql(
        Queue.SOURCE_RECORD_KEYS,
        """
        SELECT sr.id FROM source_records sr
        WHERE sr.id IN (SELECT source_record_id FROM changed WHERE is_in AND NOT was_in)
          AND sr.publication_id IS NULL
        """,
    )
    marked_contributions = enqueue_sql(
        Queue.CONTRIBUTION_ATTRIBUTES,
        """
        SELECT gm.contribution_id FROM aligned_source_contributions gm
        WHERE gm.source_contribution_id IN (SELECT id FROM changed)
        """,
    )
    scope = "AND sc.id = ANY(:source_contribution_ids)" if scoped else ""
    return f"""
        WITH computed AS (
            {source_contribution_perimeter_evidence("source_contribution_ids" if scoped else None)}
        ), target AS (
            SELECT id, evidence FROM computed
            UNION ALL
            SELECT sc.id, {NO_PERIMETER_EVIDENCE}
            FROM source_contributions sc
            LEFT JOIN computed c ON c.id = sc.id
            WHERE sc.in_perimeter AND c.id IS NULL {scope}
        ), changed AS (
            UPDATE source_contributions sc
            SET perimeter_evidence = t.evidence
            FROM target t
            WHERE sc.id = t.id AND sc.perimeter_evidence IS DISTINCT FROM t.evidence
            RETURNING sc.id, sc.source_record_id, old.in_perimeter AS was_in, new.in_perimeter AS is_in
        ), marked AS ({marked}), marked_contributions AS ({marked_contributions})
        SELECT count(*) FILTER (WHERE is_in AND NOT was_in) AS added,
               count(*) FILTER (WHERE was_in AND NOT is_in) AS removed
        FROM changed
    """


_SYNC_ALL = text(_sync_sql(scoped=False))
_SYNC_SCOPED = text(_sync_sql(scoped=True))


def refresh_source_contribution_structures(conn: Connection) -> None:
    """Rafraîchit la vue matérialisée `source_contribution_structures`, qui alimente `sync_perimeter_evidence`.

    À appeler après la matérialisation de `perimeter_structures` et la résolution des adresses, et avant le rafraîchissement de `contribution_structures`, qui en dérive.
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY source_contribution_structures"))


def sync_perimeter_evidence(
    conn: Connection, *, perimeter_ids: list[int], source_contribution_ids: list[int] | None = None
) -> InPerimeterSyncCounts:
    """Aligne les indices des contributions sources sur leur calcul, pour toutes ou pour la liste donnée. Renvoie le nombre d'entrées et de sorties du périmètre."""
    if source_contribution_ids is None:
        row = conn.execute(_SYNC_ALL, {"perimeter_ids": perimeter_ids}).one()
    else:
        row = conn.execute(
            _SYNC_SCOPED,
            {"perimeter_ids": perimeter_ids, "source_contribution_ids": source_contribution_ids},
        ).one()
    return InPerimeterSyncCounts(added=row.added, removed=row.removed)


class SourceContributionPerimeterRecompute:
    """Recalcul ciblé du périmètre après une correction d'adresse par l'administration, pour l'API."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def recompute_perimeter(
        self,
        source_contribution_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Rafraîchit la vue matérialisée `source_contribution_structures`, puis recalcule les indices des contributions sources données, de leurs contributions et de leurs publications, par les mêmes requêtes que le pipeline."""
        refresh_source_contribution_structures(self._conn)
        sync_perimeter_evidence(
            self._conn,
            perimeter_ids=perimeter_structure_ids,
            source_contribution_ids=source_contribution_ids,
        )
        self._conn.execute(
            text(
                propagate_contribution_attributes_sql(
                    "SELECT contribution_id FROM aligned_source_contributions"
                    " WHERE source_contribution_id = ANY(:source_contribution_ids)"
                )
            ),
            {"source_contribution_ids": source_contribution_ids},
        )
        publication_ids = self._conn.execute(
            text("""
                SELECT DISTINCT sr.publication_id
                FROM source_contributions sc
                JOIN source_records sr ON sr.id = sc.source_record_id
                WHERE sc.id = ANY(:ids) AND sr.publication_id IS NOT NULL
                ORDER BY 1
            """),
            {"ids": source_contribution_ids},
        ).scalars()
        refresh_publications_perimeter_evidence(self._conn, publication_ids=list(publication_ids))
