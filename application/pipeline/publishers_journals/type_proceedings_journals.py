"""Sous-étape de la phase `publishers_journals` — type en recueil d'actes les revues qui en sont.

Deux règles de `domain/journals/containers.py` désignent un recueil d'actes :

- une revue de type `unknown` dont la majorité stricte des documents sont des articles de congrès, d'après le type brut de chaque document, toutes sources confondues ;
- une revue sans ISSN, de n'importe quel type, dont le titre nomme une édition datée (« NuFACT 2022 », « 2024 IEEE SENSORS »).
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.publishers_journals._journal_label import journal_label
from application.ports.pipeline.journals import JournalProceedingsTypingQueries
from domain.journals.containers import holds_mostly_conference_papers, is_dated_event_without_issn
from domain.journals.journal import JournalType

_BY_RECORDS = "articles de congrès"
_BY_TITLE = "titre daté"


def run_type_proceedings_journals(
    logger: logging.Logger, *, journal_repo: JournalProceedingsTypingQueries
) -> PhaseMetrics:
    """Type en recueil d'actes les revues que désigne l'une des deux règles, et journalise chacune avec la règle qui la désigne."""
    metrics = PhaseMetrics()
    reasons: dict[int, str] = {
        journal.journal_id: _BY_RECORDS
        for journal in journal_repo.find_record_types_of_unknown_journals()
        if holds_mostly_conference_papers(journal.records)
    }
    for journal in journal_repo.find_titles_of_non_proceedings_journals():
        if journal.id not in reasons and is_dated_event_without_issn(
            journal.title, has_issn=journal.has_issn
        ):
            reasons[journal.id] = _BY_TITLE
    if not reasons:
        return metrics
    if len(reasons) == 1:
        etape(logger, "Typage d'une revue en recueil d'actes")
    else:
        etape(logger, "Typage de %d revues en recueils d'actes", len(reasons))
    summaries = journal_repo.describe_journals(list(reasons))
    for journal_id, reason in reasons.items():
        journal_repo.set_journal_type(journal_id, JournalType.PROCEEDINGS)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Revue typée recueil d'actes (%s) : %s",
            reason,
            journal_label(summaries[journal_id]),
            extra={"detail": True},
        )
    metrics.add(total=len(reasons), journals_typed_proceedings=len(reasons))
    logger.info(
        "%sTerminé : %s",
        DERNIERE_BRANCHE,
        accord(len(reasons), "revue typée recueil d'actes", "revues typées recueils d'actes"),
    )
    return metrics
