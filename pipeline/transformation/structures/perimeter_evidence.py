"""Indices de l'entrée des contributions sources dans le périmètre : synchronisation de `source_authorships.perimeter_evidence` sur la vue `source_authorship_structures` et l'identité des personnes RH. Partagée par la phase `affiliations` et le recalcul ciblé après une correction d'adresse (`SourceContributionPerimeterRecompute`)."""

from typing import NamedTuple

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import (
    NO_PERIMETER_EVIDENCE,
    SIGNATURES_SCOPE,
    propagate_authorship_attributes_sql,
    signature_perimeter_evidence,
)
from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)


class InPerimeterSyncCounts(NamedTuple):
    """Nombre de `source_authorships` entrées dans le périmètre et sorties du périmètre lors d'une synchronisation."""

    added: int
    removed: int


def _sync_sql(scoped: bool) -> str:
    """Synchronisation de `perimeter_evidence` sur les indices calculés, restreinte aux signatures `:signature_ids` quand `scoped` est vrai.

    Seules les signatures dont les indices changent sont écrites. Un enregistrement sans publication dont une signature entre dans le périmètre est marqué `keys_dirty` : la phase `publications` le met alors en publication.
    """
    scope = "AND sa.id = ANY(:signature_ids)" if scoped else ""
    return f"""
        WITH computed AS (
            {signature_perimeter_evidence("signature_ids" if scoped else None)}
        ), target AS (
            SELECT id, evidence FROM computed
            UNION ALL
            SELECT sa.id, {NO_PERIMETER_EVIDENCE}
            FROM source_authorships sa
            LEFT JOIN computed c ON c.id = sa.id
            WHERE sa.in_perimeter AND c.id IS NULL {scope}
        ), changed AS (
            UPDATE source_authorships sa
            SET perimeter_evidence = t.evidence
            FROM target t
            WHERE sa.id = t.id AND sa.perimeter_evidence IS DISTINCT FROM t.evidence
            RETURNING sa.source_publication_id, old.in_perimeter AS was_in, new.in_perimeter AS is_in
        ), marked AS (
            UPDATE source_publications
            SET keys_dirty = TRUE
            WHERE id IN (SELECT source_publication_id FROM changed WHERE is_in AND NOT was_in)
              AND publication_id IS NULL AND NOT keys_dirty
            RETURNING 1
        )
        SELECT count(*) FILTER (WHERE is_in AND NOT was_in) AS added,
               count(*) FILTER (WHERE was_in AND NOT is_in) AS removed
        FROM changed
    """


_SYNC_ALL = text(_sync_sql(scoped=False))
_SYNC_SCOPED = text(_sync_sql(scoped=True))


def refresh_source_authorship_structures(conn: Connection) -> None:
    """Rafraîchit la matview `source_authorship_structures`, qui alimente `sync_perimeter_evidence`.

    À appeler après la matérialisation de `perimeter_structures` et la résolution des adresses, et avant le rafraîchissement de `authorship_structures`, qui en dérive.
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY source_authorship_structures"))


def sync_perimeter_evidence(
    conn: Connection, *, perimeter_ids: list[int], signature_ids: list[int] | None = None
) -> InPerimeterSyncCounts:
    """Aligne `source_authorships.perimeter_evidence` sur les indices calculés (`signature_perimeter_evidence`), pour toutes les signatures ou pour `signature_ids`."""
    if signature_ids is None:
        row = conn.execute(_SYNC_ALL, {"perimeter_ids": perimeter_ids}).one()
    else:
        row = conn.execute(
            _SYNC_SCOPED, {"perimeter_ids": perimeter_ids, "signature_ids": signature_ids}
        ).one()
    return InPerimeterSyncCounts(added=row.added, removed=row.removed)


class SourceContributionPerimeterRecompute:
    """Recalcul ciblé du périmètre après une correction d'adresse par l'administration (port injecté par l'API)."""

    def recompute_perimeter(
        self,
        conn: Connection,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Rafraîchit la matview `source_authorship_structures`, puis recalcule les indices des contributions sources données, de leurs contributions et de leurs publications, par les mêmes requêtes que le pipeline."""
        refresh_source_authorship_structures(conn)
        sync_perimeter_evidence(
            conn, perimeter_ids=perimeter_structure_ids, signature_ids=source_authorship_ids
        )
        conn.execute(
            text(propagate_authorship_attributes_sql(scope=SIGNATURES_SCOPE)),
            {"signature_ids": source_authorship_ids},
        )
        publication_ids = conn.execute(
            text("""
                SELECT DISTINCT sp.publication_id
                FROM source_authorships sa
                JOIN source_publications sp ON sp.id = sa.source_publication_id
                WHERE sa.id = ANY(:ids) AND sp.publication_id IS NOT NULL
                ORDER BY 1
            """),
            {"ids": source_authorship_ids},
        ).scalars()
        refresh_publications_perimeter_evidence(conn, publication_ids=list(publication_ids))
