"""Sous-étape de la phase `publishers_journals` — fusionne les monographies en double.

Deux monographies de même titre naissent quand l'éditeur ou l'ISBN manque à l'une des sources, puis arrive par une autre. `duplicate_monographs` (`domain/monographs/matching.py`) désigne les fusions : une monographie rejoint la seule monographie compatible de son titre, quand celle-ci en dit davantage. Le journal garde le titre et les identifiants de chaque fusion.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.monographs import MonographMergeQueries
from domain.monographs.matching import duplicate_monographs


def run_merge_duplicate_monographs(
    logger: logging.Logger, *, monograph_repo: MonographMergeQueries
) -> PhaseMetrics:
    """Fusionne les monographies en double et journalise chaque fusion."""
    merges = [
        (group.title, target, source)
        for group in monograph_repo.find_monographs_sharing_a_title()
        for target, source in duplicate_monographs(group.monographs)
    ]
    metrics = PhaseMetrics()
    if not merges:
        return metrics
    if len(merges) == 1:
        etape(logger, "Fusion d'une monographie en double")
    else:
        etape(logger, "Fusion de %d monographies en double", len(merges))
    for title, target, source in merges:
        monograph_repo.merge_monograph_into(target, source)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie %d fusionnée dans %d : « %s »",
            source,
            target,
            title,
            extra={"detail": True},
        )
    metrics.add(total=len(merges), monographs_merged=len(merges))
    logger.info(
        "%sTerminé : %s",
        DERNIERE_BRANCHE,
        accord(len(merges), "monographie fusionnée", "monographies fusionnées"),
    )
    return metrics
