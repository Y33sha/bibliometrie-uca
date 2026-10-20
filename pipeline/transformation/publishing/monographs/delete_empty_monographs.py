"""Sous-étape de la phase `authorships` — supprime les monographies vides.

Une monographie vide n'est portée par aucun enregistrement ni aucune publication. Elle se vide quand ses enregistrements rejoignent une autre monographie, par exemple quand l'ISBN arrive sur une monographie créée par son titre. Une monographie encore portée par une publication attend que la phase `publications` recalcule celle-ci. Le journal garde le titre de chaque monographie supprimée.
"""

import logging

from pipeline.runtime.observability.libelles import accord
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.monographs.monographs import MonographGatewayQueries

LIBELLE = "Monographies vides"
"""Libellé de la sous-étape dans le journal de la phase."""


def run_delete_empty_monographs(
    logger: logging.Logger, *, monograph_repo: MonographGatewayQueries
) -> PhaseMetrics:
    """Supprime les monographies vides et journalise chacune."""
    deleted = monograph_repo.delete_empty_monographs()
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    for monograph_id, title in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie vide supprimée : %d « %s »", monograph_id, title, extra={"detail": True}
        )
    metrics.add(seen=len(deleted), monographs_deleted=len(deleted))
    metrics.report = accord(len(deleted), "monographie supprimée", "monographies supprimées")
    return metrics
