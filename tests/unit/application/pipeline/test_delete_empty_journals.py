"""Tests de la suppression des revues vides (`application.pipeline.publishers_journals.delete_empty_journals`)."""

import logging

from application.pipeline.publishers_journals.delete_empty_journals import (
    run_delete_empty_journals,
)
from application.ports.pipeline.journals import JournalSummary


class _Repo:
    def __init__(self, deleted: list[JournalSummary]) -> None:
        self._deleted = deleted

    def delete_empty_journals(self) -> list[JournalSummary]:
        return self._deleted


def test_each_deleted_journal_is_logged_with_its_publisher_and_issns(caplog):
    logger = logging.getLogger("test_revues_vides")
    deleted = [JournalSummary(101021, "Livestock Science", "IntechOpen", None, None)]
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_delete_empty_journals(logger, journal_repo=_Repo(deleted))
    assert metrics.extras["journals_deleted"] == 1
    assert "101021 « Livestock Science » (IntechOpen, sans ISSN)" in caplog.text


def test_without_empty_journal_nothing_is_logged(caplog):
    logger = logging.getLogger("test_revues_vides_aucune")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_delete_empty_journals(logger, journal_repo=_Repo([]))
    assert metrics.total == 0
    assert caplog.text == ""
