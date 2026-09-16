"""Sous-étape de la phase `publishers_journals` — fusionne les revues qui partagent leur ISSN-L.

L'ISSN-L vient des notices Sudoc : deux revues vérifiées qui le partagent décrivent la même publication. La revue qui porte le plus de publications absorbe les autres ; à égalité, celle dont l'identifiant est le plus petit. La fusion elle-même est celle de l'administration des revues, injectée par le composition-root : publications et métadonnées passent à la cible, qui est ensuite requalifiée, puis la source est supprimée.
"""

import logging
from collections.abc import Callable

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.ports.pipeline.journals import JournalMergeQueries

MergeJournals = Callable[[int, int], None]
"""`(cible, source)` : fusionne la revue source dans la cible et valide la transaction."""


def run_merge_journals_by_issnl(
    logger: logging.Logger,
    *,
    journal_repo: JournalMergeQueries,
    merge: MergeJournals,
) -> PhaseMetrics:
    """Fusionne chaque groupe de revues de même ISSN-L."""
    groups = journal_repo.find_journals_sharing_issnl()
    metrics = PhaseMetrics()
    if not groups:
        return metrics
    metrics.add(total=len(groups))
    etape(
        logger,
        "%s : fusion des revues de même ISSN-L",
        accord(len(groups), "groupe de revues", "groupes de revues"),
    )
    with progression(len(groups), BRANCHE.rstrip(), logger) as avancement:
        for group in groups:
            target, sources = group.journal_ids[0], group.journal_ids[1:]
            for source in sources:
                merge(target, source)
                # Ligne de détail : le terminal la masque, le journal la garde.
                logger.info(
                    "ISSN-L %s : la revue %d absorbe la revue %d",
                    group.issnl,
                    target,
                    source,
                    extra={"detail": True},
                )
            metrics.add(journals_merged=len(sources))
            avancement.avance()
    logger.info(
        "%sTerminé : %s",
        DERNIERE_BRANCHE,
        accord(metrics.extras.get("journals_merged", 0), "revue fusionnée", "revues fusionnées"),
    )
    return metrics
