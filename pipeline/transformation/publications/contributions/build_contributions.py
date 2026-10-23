"""Tâche `contributions.build` : liens de la table consolidée `contributions`, à partir des `source_contributions`.

Insère les contributions manquantes puis supprime les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste). Les tâches suivantes de la phase recomposent les attributs, le périmètre des publications et les matviews.
"""

import logging

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import insert_missing_contributions_sql
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting


def insert_missing_contributions(conn: Connection) -> int:
    """Insère les couples (publication, personne) attestés par une contribution source et absents de `contributions`."""
    return conn.execute(text(insert_missing_contributions_sql())).rowcount


def prune_orphan_contributions(conn: Connection) -> int:
    """Supprime les contributions qu'aucune contribution source n'atteste plus."""
    return conn.execute(
        text("""
            DELETE FROM contributions a
            WHERE NOT EXISTS (
                SELECT 1
                FROM source_contributions sc
                JOIN source_records sr ON sr.id = sc.source_record_id
                WHERE sc.person_id = a.person_id
                  AND sr.publication_id = a.publication_id
            )
        """)
    ).rowcount


def build(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Ajoute les liens attestés et retire ceux que plus aucune source n'atteste. Idempotent."""
    step(logger, "Liens publication-personne")

    # Étape 1 : Ajoute les paires attestées absentes, retire les orphelines.
    with waiting(f"{BRANCH}création des liens en cours", logger) as line:
        inserted = insert_missing_contributions(conn)
        line.conclude(
            f"{BRANCH}{quantity(inserted, 'nouveau lien', 'nouveaux liens')} {inflect(inserted, 'créé')}"
        )
    with waiting(f"{LAST_BRANCH}suppression des liens obsolètes en cours", logger) as line:
        pruned = prune_orphan_contributions(conn)
        line.conclude(
            f"{LAST_BRANCH}{quantity(pruned, 'lien')} {inflect(pruned, 'obsolète')} {inflect(pruned, 'supprimé')}"
        )

    metrics = PhaseMetrics()
    metrics.add(new=inserted)
    metrics.details["summary"] = {"created": inserted, "pruned": pruned}
    return metrics
