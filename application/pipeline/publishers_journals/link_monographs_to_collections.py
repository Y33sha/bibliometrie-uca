"""Sous-étape de la phase `publishers_journals` — rattache chaque monographie à sa collection.

La collection d'une monographie est la seule entrée de `journals` à ISSN que portent ses enregistrements. Sans elle, la monographie garde son `journal_id`. Une monographie dont les enregistrements portent plusieurs entrées à ISSN est signalée, sans changement : rien ne dit laquelle est sa collection. Le calcul se refait à chaque run, d'après les enregistrements.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.monographs import MonographCollectionQueries


def run_link_monographs_to_collections(
    logger: logging.Logger, *, monograph_repo: MonographCollectionQueries
) -> PhaseMetrics:
    """Rattache les monographies à leur collection, et journalise chaque rattachement et chaque conflit."""
    links = monograph_repo.link_monographs_to_collections()
    conflicts = monograph_repo.find_monograph_collection_conflicts()
    metrics = PhaseMetrics()
    if not (links or conflicts):
        return metrics
    etape(logger, "Rattachement des monographies à leur collection")
    for link in links:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie %d « %s » rattachée à la collection %d « %s » (au lieu de %s)",
            link.monograph_id,
            link.title,
            link.collection_id,
            link.collection_title,
            link.previous_id,
            extra={"detail": True},
        )
    for conflict in conflicts:
        logger.warning(
            "Monographie %d « %s » : plusieurs collections possibles %s — laissée en l'état",
            conflict.monograph_id,
            conflict.title,
            list(conflict.candidate_ids),
            extra={"detail": True},
        )
    metrics.add(
        total=len(links) + len(conflicts),
        monographs_linked=len(links),
        monograph_collection_conflicts=len(conflicts),
    )
    logger.info(
        "%sTerminé : %s, %s",
        DERNIERE_BRANCHE,
        accord(len(links), "monographie rattachée", "monographies rattachées"),
        accord(len(conflicts), "conflit", "conflits"),
    )
    return metrics
