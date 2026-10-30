"""Cycle de vie d'une publication : création, suppression après recalcul, dissolution, purge.

Une publication existe si elle a au moins un enregistrement source, un type admissible et au moins une contribution rattachée à une personne. `refresh` vérifie les deux premières conditions après le recalcul d'une publication. `purge_publications` vérifie la première et la dernière sur toute la table, une fois les personnes résolues.
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
    """Crée une publication avec les seules valeurs exigées par la table, et renvoie son id.

    Ces valeurs tiennent jusqu'au premier `refresh` : le titre est le titre normalisé, le type vaut `other` quand la source n'en donne aucun, le statut open access vaut la valeur par défaut.
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
    """Recalcule la publication depuis ses enregistrements sources. La supprime si elle est sans enregistrement source ou si son type est inadmissible. Renvoie le verdict du recalcul."""
    verdict = refresh_from_sources(conn, publication_id)
    if verdict in _DELETION_VERDICTS:
        PublicationStore(conn).delete(publication_id)
    return verdict


def dissolve(conn: Connection, publication_id: int, successor_id: int) -> None:
    """Supprime une publication dont tous les enregistrements sources ont rejoint le successeur. Ses paiements APC passent au successeur, et son identifiant redirige vers lui.

    Raises:
        ValueError: un enregistrement source reste rattaché à la publication.
    """
    store = PublicationStore(conn)
    if store.has_source_records(publication_id):
        raise ValueError(
            f"Publication {publication_id} dissoute avec des source_records rattachées"
        )
    store.repoint_dependents(publication_id, successor_id)
    store.delete(publication_id)


def purge_publications(conn: Connection, *, limit: int | None = None) -> int:
    """Supprime les publications sans enregistrement source ou sans contribution rattachée à une personne, `limit` au plus. Renvoie le nombre de publications supprimées.

    Une publication perd son dernier enregistrement source quand la phase `normalize` retire un enregistrement source disparu de sa source. Elle perd sa dernière contribution rattachée à une personne par un rejet, une forme de nom rejetée ou une personne supprimée. Ses sujets sont supprimés avec elle (`ON DELETE CASCADE`).
    """
    limit_clause = "LIMIT :lim" if limit is not None else ""
    return conn.execute(
        text(f"""
            DELETE FROM publications
            WHERE id IN (
                SELECT p.id FROM publications p
                WHERE NOT EXISTS (SELECT 1 FROM source_records sr WHERE sr.publication_id = p.id)
                   OR NOT EXISTS (
                       SELECT 1 FROM contributions g
                       WHERE g.publication_id = p.id AND g.person_id IS NOT NULL
                   )
                {limit_clause}
            )
        """),
        {"lim": limit} if limit is not None else {},
    ).rowcount
