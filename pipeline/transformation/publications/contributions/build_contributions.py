"""Tâche `contributions.build` : liens de la table consolidée `contributions`, à partir des `source_contributions`.

Insère les contributions manquantes puis supprime les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste). Les tâches suivantes de la phase recomposent les attributs, le périmètre des publications et les matviews.
"""

import logging

from sqlalchemy import Connection

from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.publications.contributions.contributions_queries import (
    ContributionsBuild,
)


def build(
    conn: Connection,
    queries: ContributionsBuild,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Ajoute les liens attestés et retire ceux que plus aucune source n'atteste. Idempotent."""
    etape(logger, "Liens publication-personne")

    # Étape 1 : Ajoute les paires attestées absentes, retire les orphelines.
    with attente(f"{BRANCHE}création des liens en cours", logger) as ligne:
        inserted = queries.insert_missing_contributions(conn)
        ligne.conclut(
            f"{BRANCHE}{accord(inserted, 'nouveau lien', 'nouveaux liens')} {forme(inserted, 'créé')}"
        )
    with attente(f"{DERNIERE_BRANCHE}suppression des liens obsolètes en cours", logger) as ligne:
        pruned = queries.prune_orphan_contributions(conn)
        ligne.conclut(
            f"{DERNIERE_BRANCHE}{accord(pruned, 'lien')} {forme(pruned, 'obsolète')} {forme(pruned, 'supprimé')}"
        )

    metrics = PhaseMetrics()
    metrics.add(new=inserted)
    metrics.details["summary"] = {"created": inserted, "pruned": pruned}
    return metrics
