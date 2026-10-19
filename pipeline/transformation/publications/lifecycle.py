"""Cycle de vie d'une publication : suppression après recalcul, dissolution, suppression des publications sans source.

Une publication existe si elle a au moins une `source_publication`, un type admissible et au moins une authorship. `refresh` vérifie la `source_publication` et le type après le recalcul d'une publication. `delete_publications_without_sources` vérifie la `source_publication` sur toute la table. La phase `authorships` supprime les publications sans authorship (`purge_orphan_publications`).
"""

from sqlalchemy import Connection, text

from pipeline.transformation.publications.reconciliation.refresh import (
    PublicationStore,
    RefreshVerdict,
    refresh_from_sources,
)

_DELETION_VERDICTS = frozenset({RefreshVerdict.NO_SOURCE, RefreshVerdict.INADMISSIBLE_TYPE})


def refresh(store: PublicationStore, publication_id: int) -> RefreshVerdict:
    """Recalcule la publication depuis ses `source_publications`, et la supprime si elle n'en a plus ou si son type n'est pas admissible. Rend le verdict du recalcul."""
    verdict = refresh_from_sources(publication_id, repo=store)
    if verdict in _DELETION_VERDICTS:
        store.delete(publication_id)
    return verdict


def dissolve(store: PublicationStore, publication_id: int, successor_id: int) -> None:
    """Supprime une publication dont toutes les `source_publications` ont rejoint `successor_id`. Ses paiements APC passent au successeur, et son identifiant redirige vers lui.

    Lève `ValueError` si une `source_publication` est encore rattachée à la publication.
    """
    if store.has_source_publications(publication_id):
        raise ValueError(
            f"Publication {publication_id} dissoute avec des source_publications rattachées"
        )
    store.repoint_dependents(publication_id, successor_id)
    store.delete(publication_id)


def delete_publications_without_sources(conn: Connection) -> int:
    """Supprime les publications auxquelles plus aucune `source_publication` n'est rattachée. Rend le nombre de publications supprimées."""
    return conn.execute(
        text("""
            DELETE FROM publications p
            WHERE NOT EXISTS (
                SELECT 1 FROM source_publications sp WHERE sp.publication_id = p.id
            )
        """)
    ).rowcount
