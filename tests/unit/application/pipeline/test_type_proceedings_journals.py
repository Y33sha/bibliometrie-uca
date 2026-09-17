"""Tests du typage en recueil d'actes (`application.pipeline.publishers_journals.type_proceedings_journals`)."""

import logging
from collections.abc import Sequence

from application.pipeline.publishers_journals.type_proceedings_journals import (
    run_type_proceedings_journals,
)
from application.ports.pipeline.journals import JournalRecordTypes, JournalSummary
from domain.journals.journal import JournalType


class _Repo:
    def __init__(self, journals: list[JournalRecordTypes]) -> None:
        self._journals = journals
        self.types: dict[int, JournalType] = {}

    def find_record_types_of_unknown_journals(self) -> list[JournalRecordTypes]:
        return self._journals

    def describe_journals(self, journal_ids: Sequence[int]) -> dict[int, JournalSummary]:
        return {i: JournalSummary(i, f"Revue {i}", None, None, None) for i in journal_ids}

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        self.types[journal_id] = journal_type


def test_revue_d_articles_de_congres_typee_et_journalisee(caplog):
    """Cas réel : actes IEEE ROBIO 2018, quatre articles de congrès Crossref."""
    logger = logging.getLogger("test_recueils")
    repo = _Repo(
        [
            JournalRecordTypes(95637, (("crossref", "proceedings-article"),) * 4),
            JournalRecordTypes(12, (("crossref", "journal-article"), ("hal", "COMM"))),
        ]
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_type_proceedings_journals(logger, journal_repo=repo)

    assert repo.types == {95637: JournalType.PROCEEDINGS}
    assert metrics.extras["journals_typed_proceedings"] == 1
    assert "95637 « Revue 95637 » (sans éditeur, sans ISSN)" in caplog.text


def test_sans_recueil_rien_n_est_journalise(caplog):
    logger = logging.getLogger("test_recueils_aucun")
    repo = _Repo([JournalRecordTypes(12, (("hal", "ART"),))])
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_type_proceedings_journals(logger, journal_repo=repo)

    assert repo.types == {}
    assert metrics.total == 0
    assert caplog.text == ""
