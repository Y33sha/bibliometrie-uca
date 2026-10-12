"""Sous-étape de la phase `publishers_journals` — supprime les éditeurs vides.

Un éditeur vide ne porte ni revue, ni monographie, ni préfixe DOI, ni paiement APC, ni forme de nom de revue. Une forme de nom de revue rattachée à un éditeur retrouve une revue par son titre chez cet éditeur : l'éditeur qui la porte reste. Ses propres formes de nom partent avec lui. Le journal garde le nom de chaque éditeur supprimé.
"""

import logging

from pipeline.publishing.publishers.publishers import PublisherGatewayQueries
from pipeline.runtime.libelles import accord
from pipeline.runtime.metrics import PhaseMetrics

LIBELLE = "Éditeurs vides"
"""Libellé de la sous-étape dans le journal de la phase."""


def run_delete_empty_publishers(
    logger: logging.Logger, *, publisher_repo: PublisherGatewayQueries
) -> PhaseMetrics:
    """Supprime les éditeurs vides et journalise chacun."""
    deleted = publisher_repo.delete_empty_publishers()
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    for publisher_id, name in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info("Éditeur vide supprimé : %d « %s »", publisher_id, name, extra={"detail": True})
    metrics.add(total=len(deleted), publishers_deleted=len(deleted))
    metrics.resume = accord(len(deleted), "éditeur supprimé", "éditeurs supprimés")
    return metrics
