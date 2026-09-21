"""Sous-étape de la phase `publishers_journals` — supprime les monographies vides.

Une monographie vide n'est portée par aucun enregistrement ni aucune publication. Elle se vide quand ses enregistrements rejoignent une autre monographie, par exemple quand l'ISBN arrive sur une monographie créée par son titre. Une monographie encore portée par une publication attend que la phase `publications` recalcule celle-ci. Le journal garde le titre de chaque monographie supprimée.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.monographs import MonographCleanupQueries


def run_delete_empty_monographs(
    logger: logging.Logger, *, monograph_repo: MonographCleanupQueries
) -> PhaseMetrics:
    """Supprime les monographies vides et journalise chacune."""
    deleted = monograph_repo.delete_empty_monographs()
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    if len(deleted) == 1:
        etape(logger, "Suppression d'une monographie vide")
    else:
        etape(logger, "Suppression des %d monographies vides", len(deleted))
    for monograph_id, title in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie vide supprimée : %d « %s »", monograph_id, title, extra={"detail": True}
        )
    metrics.add(total=len(deleted), monographs_deleted=len(deleted))
    logger.info(
        "%sTerminé : %s",
        DERNIERE_BRANCHE,
        accord(len(deleted), "monographie supprimée", "monographies supprimées"),
    )
    return metrics
