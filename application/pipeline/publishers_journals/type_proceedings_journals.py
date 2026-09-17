"""Sous-étape de la phase `publishers_journals` — type en recueil d'actes les revues de type inconnu.

Une revue de type `unknown` dont la majorité stricte des documents sont des articles de congrès devient `proceedings`. Le type brut de chaque document est lu, toutes sources confondues (`domain/journals/containers.py`). Les autres types de revue restent en place.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.publishers_journals._journal_label import journal_label
from application.ports.pipeline.journals import JournalProceedingsTypingQueries
from domain.journals.containers import holds_mostly_conference_papers
from domain.journals.journal import JournalType


def run_type_proceedings_journals(
    logger: logging.Logger, *, journal_repo: JournalProceedingsTypingQueries
) -> PhaseMetrics:
    """Type en recueil d'actes les revues de type inconnu qui contiennent surtout des articles de congrès, et journalise chacune."""
    metrics = PhaseMetrics()
    typed = [
        journal.journal_id
        for journal in journal_repo.find_record_types_of_unknown_journals()
        if holds_mostly_conference_papers(journal.records)
    ]
    if not typed:
        return metrics
    if len(typed) == 1:
        etape(logger, "Typage d'une revue en recueil d'actes")
    else:
        etape(logger, "Typage de %d revues en recueils d'actes", len(typed))
    summaries = journal_repo.describe_journals(typed)
    for journal_id in typed:
        journal_repo.set_journal_type(journal_id, JournalType.PROCEEDINGS)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Revue typée recueil d'actes : %s",
            journal_label(summaries[journal_id]),
            extra={"detail": True},
        )
    metrics.add(total=len(typed), journals_typed_proceedings=len(typed))
    logger.info(
        "%sTerminé : %s",
        DERNIERE_BRANCHE,
        accord(len(typed), "revue typée recueil d'actes", "revues typées recueils d'actes"),
    )
    return metrics
