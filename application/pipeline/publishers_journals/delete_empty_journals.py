"""Sous-étape de la phase `publishers_journals` — supprime les revues vides.

Une revue vide n'a ni enregistrement, ni publication, ni paiement APC. Ses formes de nom partent avec elle : un enregistrement qui porte plus tard ce titre chez cet éditeur crée de nouveau sa revue. Le journal garde le titre, l'éditeur et les ISSN de chaque revue supprimée.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.publishers_journals._journal_label import journal_label
from application.ports.pipeline.journals import JournalCleanupQueries


def run_delete_empty_journals(
    logger: logging.Logger, *, journal_repo: JournalCleanupQueries
) -> PhaseMetrics:
    """Supprime les revues vides et journalise chacune."""
    deleted = journal_repo.delete_empty_journals()
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    etape(
        logger,
        "%s : suppression des revues vides",
        accord(len(deleted), "revue vide", "revues vides"),
    )
    for journal in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info("Revue vide supprimée : %s", journal_label(journal), extra={"detail": True})
    metrics.add(total=len(deleted), journals_deleted=len(deleted))
    logger.info(
        "%sTerminé : %s",
        DERNIERE_BRANCHE,
        accord(len(deleted), "revue supprimée", "revues supprimées"),
    )
    return metrics
