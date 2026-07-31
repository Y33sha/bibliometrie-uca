"""Purge des publications orphelines (zéro authorship), en fin de phase authorships.

Défense en profondeur. La réconciliation ne crée une publication que pour une partition d'orphelins **in-périmètre** (gate `any(m.in_perimeter)` dans `domain.publications.reconciliation`) : une publication naît avec au moins un authorship attendu. Elle tombe à zéro authorship quand sa dernière signature in-périmètre disparaît — personne détachée, structure sortie du périmètre, forme de nom rejetée. Une telle publication rétrogradée est inatteignable dans l'UI (listes scopées périmètre, fiches personne via les authorships) ; la purge la supprime.

`publication_subjects` (FK `ON DELETE CASCADE`) suit ; `subjects.usage_count` et la matview `subject_cooccurrences` en héritent.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.authorships.purge_orphan_publications import (
    PurgeOrphanPublicationsQueries,
)


class PgPurgeOrphanPublicationsQueries(PurgeOrphanPublicationsQueries):
    """Adapter PostgreSQL pour le port `PurgeOrphanPublicationsQueries`."""

    def purge_orphan_publications(self, conn: Connection, *, limit: int | None = None) -> int:
        # Les marqueurs `distinct_publications` d'une publication purgée partent en CASCADE (cas marginal).
        limit_clause = "LIMIT :lim" if limit is not None else ""
        return conn.execute(
            text(
                f"""
                DELETE FROM publications
                WHERE id IN (
                    SELECT p.id FROM publications p
                    WHERE NOT EXISTS (
                        SELECT 1 FROM authorships a WHERE a.publication_id = p.id
                    )
                    {limit_clause}
                )
                """
            ),
            {"lim": limit} if limit is not None else {},
        ).rowcount
