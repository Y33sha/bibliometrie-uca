"""Cycle de vie d'une publication : création, suppression après recalcul, dissolution, purge.

Une publication existe si elle a au moins une `source_record`, un type admissible et au moins une contribution, groupe de contributions sources rattaché à une personne. `refresh` vérifie la `source_record` et le type après le recalcul d'une publication. `purge_publications` vérifie la `source_record` et la contribution sur toute la table, une fois les personnes résolues.
"""

from sqlalchemy import Connection, text

from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT
from pipeline.transformation.publications.consolidation import RefreshVerdict, refresh_from_sources
from pipeline.transformation.publications.store import PublicationStore

_DELETION_VERDICTS = frozenset({RefreshVerdict.NO_SOURCE, RefreshVerdict.INADMISSIBLE_TYPE})


def create(
    conn: Connection,
    *,
    title_normalized: str,
    doc_type: str | None,
    publication_year: int,
    doi: str | None,
) -> int:
    """Crée une publication semée sur le minimum requis par les colonnes NOT NULL, et rend son id.

    Les valeurs de semis tiennent jusqu'au premier `refresh` : `title` reçoit le titre normalisé, `doc_type` vaut `other` quand la source n'en donne aucun, `oa_status` vaut la valeur par défaut.
    """
    return PublicationStore(conn).create(
        title=title_normalized,
        title_normalized=title_normalized,
        doc_type=doc_type or "other",
        publication_year=publication_year,
        doi=doi,
        oa_status=OA_STATUS_UNKNOWN_DEFAULT,
    )


def refresh(conn: Connection, publication_id: int) -> RefreshVerdict:
    """Recalcule la publication depuis ses `source_records`, et la supprime si elle n'en a plus ou si son type n'est pas admissible. Rend le verdict du recalcul."""
    verdict = refresh_from_sources(conn, publication_id)
    if verdict in _DELETION_VERDICTS:
        PublicationStore(conn).delete(publication_id)
    return verdict


def dissolve(conn: Connection, publication_id: int, successor_id: int) -> None:
    """Supprime une publication dont toutes les `source_records` ont rejoint `successor_id`. Ses paiements APC passent au successeur, et son identifiant redirige vers lui.

    Lève `ValueError` si une `source_record` est encore rattachée à la publication.
    """
    store = PublicationStore(conn)
    if store.has_source_records(publication_id):
        raise ValueError(
            f"Publication {publication_id} dissoute avec des source_records rattachées"
        )
    store.repoint_dependents(publication_id, successor_id)
    store.delete(publication_id)


def purge_publications(conn: Connection, *, limit: int | None = None) -> int:
    """Supprime les publications sans `source_record` ou sans contribution, un lot de `limit` au plus. Rend le nombre de publications supprimées.

    Une publication perd sa dernière `source_record` quand la phase `normalize` retire un document disparu de sa source. Elle perd sa dernière contribution quand son dernier groupe rattaché à une personne perd sa personne : rejet, forme de nom rejetée, personne supprimée. `publication_subjects` suit par `ON DELETE CASCADE`.
    """
    limit_clause = "LIMIT :lim" if limit is not None else ""
    return conn.execute(
        text(f"""
            DELETE FROM publications
            WHERE id IN (
                SELECT p.id FROM publications p
                WHERE NOT EXISTS (SELECT 1 FROM source_records sr WHERE sr.publication_id = p.id)
                   OR NOT EXISTS (
                       SELECT 1 FROM source_contribution_groups g
                       WHERE g.publication_id = p.id AND g.person_id IS NOT NULL
                   )
                {limit_clause}
            )
        """),
        {"lim": limit} if limit is not None else {},
    ).rowcount
