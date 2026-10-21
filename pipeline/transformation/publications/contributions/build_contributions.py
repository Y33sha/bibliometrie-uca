"""Tâche `contributions.build` : liens de la table consolidée `contributions`, à partir des `source_contributions`.

Insère les contributions manquantes puis supprime les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste). Les tâches suivantes de la phase recomposent les attributs, le périmètre des publications et les matviews.
"""

import logging

from sqlalchemy import Connection

from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.publications.contributions.contributions_queries import (
    ContributionsBuild,
)


def build(
    conn: Connection,
    queries: ContributionsBuild,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Ajoute les liens attestés et retire ceux que plus aucune source n'atteste. Idempotent."""
    step(logger, "Liens publication-personne")

    # Étape 1 : Ajoute les paires attestées absentes, retire les orphelines.
    with waiting(f"{BRANCH}création des liens en cours", logger) as line:
        inserted = queries.insert_missing_contributions(conn)
        line.conclude(
            f"{BRANCH}{quantity(inserted, 'nouveau lien', 'nouveaux liens')} {inflect(inserted, 'créé')}"
        )
    with waiting(f"{LAST_BRANCH}suppression des liens obsolètes en cours", logger) as line:
        pruned = queries.prune_orphan_contributions(conn)
        line.conclude(
            f"{LAST_BRANCH}{quantity(pruned, 'lien')} {inflect(pruned, 'obsolète')} {inflect(pruned, 'supprimé')}"
        )

    metrics = PhaseMetrics()
    metrics.add(new=inserted)
    metrics.details["summary"] = {"created": inserted, "pruned": pruned}
    return metrics
