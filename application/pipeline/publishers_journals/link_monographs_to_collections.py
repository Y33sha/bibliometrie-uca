"""Sous-étape de la phase `publishers_journals` — rattache chaque monographie à sa collection.

`choose_monograph_journal` (`domain/monographs/collection.py`) choisit l'entrée de `journals` d'une monographie parmi celles que portent ses enregistrements : sa collection, à défaut le volume lui-même, à défaut aucune. Une monographie en conflit reste en l'état, signalée. Le calcul se refait à chaque run, d'après les enregistrements.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.monographs import (
    MonographCollectionQueries,
    MonographJournalCandidates,
)
from domain.monographs.collection import MonographJournalChoice, choose_monograph_journal


def run_link_monographs_to_collections(
    logger: logging.Logger, *, monograph_repo: MonographCollectionQueries
) -> PhaseMetrics:
    """Rattache les monographies à leur entrée de `journals`, et journalise chaque changement et chaque conflit."""
    changes: list[tuple[MonographJournalCandidates, MonographJournalChoice]] = []
    conflicts: list[tuple[MonographJournalCandidates, MonographJournalChoice]] = []
    for m in monograph_repo.find_monograph_journal_candidates():
        choice = choose_monograph_journal(m.with_issn, m.without_issn)
        if choice.conflict:
            conflicts.append((m, choice))
        elif choice.journal_id != m.journal_id:
            changes.append((m, choice))
    metrics = PhaseMetrics()
    if not (changes or conflicts):
        return metrics
    etape(logger, "Rattachement des monographies à leur collection")
    for m, choice in changes:
        monograph_repo.set_monograph_journal(m.monograph_id, choice.journal_id)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie %d « %s » rattachée à %s (au lieu de %s)",
            m.monograph_id,
            m.title,
            choice.journal_id,
            m.journal_id,
            extra={"detail": True},
        )
    for m, choice in conflicts:
        logger.warning(
            "Monographie %d « %s » : plusieurs rattachements possibles %s — laissée en l'état",
            m.monograph_id,
            m.title,
            list(choice.conflict),
            extra={"detail": True},
        )
    metrics.add(
        total=len(changes) + len(conflicts),
        monographs_linked=len(changes),
        monograph_collection_conflicts=len(conflicts),
    )
    logger.info(
        "%sTerminé : %s, %s",
        DERNIERE_BRANCHE,
        accord(len(changes), "monographie rattachée", "monographies rattachées"),
        accord(len(conflicts), "conflit", "conflits"),
    )
    return metrics
