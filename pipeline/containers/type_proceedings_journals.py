"""Sous-étape de la phase `publishers_journals` — type en recueil d'actes les revues qui en sont.

Trois règles de `domain/journals/containers.py` désignent un recueil d'actes :

- une revue de type `unknown` dont la majorité stricte des documents sont des articles de congrès, d'après le type brut de chaque document, toutes sources confondues ;
- une revue sans ISSN, de n'importe quel type, dont le titre nomme une édition datée (« NuFACT 2022 », « 2024 IEEE SENSORS ») ;
- une revue sans ISSN, de n'importe quel type, dont le titre annonce des actes, hors société savante, académie et institution.
"""

import logging

from application.ports.pipeline.journals import JournalProceedingsTypingQueries
from domain.journals.containers import (
    holds_mostly_conference_papers,
    is_dated_event_without_issn,
    is_proceedings_title_without_issn,
)
from domain.journals.journal import JournalType
from pipeline.containers.journal_label import journal_label
from pipeline.libelles import accord
from pipeline.metrics import PhaseMetrics

LIBELLE = "Typage des recueils d'actes"
"""Libellé de la sous-étape dans le journal de la phase."""

_BY_RECORDS = "articles de congrès"
_BY_DATED_TITLE = "titre daté"
_BY_PROCEEDINGS_TITLE = "titre d'actes"


def run_type_proceedings_journals(
    logger: logging.Logger, *, journal_repo: JournalProceedingsTypingQueries
) -> PhaseMetrics:
    """Type en recueil d'actes les revues que désigne l'une des trois règles, et journalise chacune avec la règle qui la désigne."""
    metrics = PhaseMetrics()
    reasons: dict[int, str] = {
        journal.journal_id: _BY_RECORDS
        for journal in journal_repo.find_record_types_of_unknown_journals()
        if holds_mostly_conference_papers(journal.records)
    }
    for journal in journal_repo.find_titles_of_non_proceedings_journals():
        if journal.id in reasons:
            continue
        if is_dated_event_without_issn(journal.title, has_issn=journal.has_issn):
            reasons[journal.id] = _BY_DATED_TITLE
        elif is_proceedings_title_without_issn(journal.title, has_issn=journal.has_issn):
            reasons[journal.id] = _BY_PROCEEDINGS_TITLE
    if not reasons:
        return metrics
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
    metrics.resume = accord(
        len(reasons), "revue typée recueil d'actes", "revues typées recueils d'actes"
    )
    return metrics
