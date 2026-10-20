"""Tests de la suppression des revues vides (`pipeline.transformation.publishing.journals.delete_empty_journals`)."""

import contextlib
import logging

import pytest

from pipeline.transformation.publishing.journals import delete_empty_journals as step
from pipeline.transformation.publishing.journals.store import JournalSummary


class _Repo:
    def __init__(self, deleted: list[JournalSummary]) -> None:
        self._deleted = deleted

    def delete_empty_journals(self) -> list[JournalSummary]:
        return self._deleted


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            step, "delete_empty_journals", lambda conn, *a, **k: repo.delete_empty_journals(*a, **k)
        )
        yield


def test_each_deleted_journal_is_logged_with_its_publisher_and_issns(caplog):
    logger = logging.getLogger("test_revues_vides")
    deleted = [JournalSummary(101021, "Livestock Science", "IntechOpen", ())]
    with caplog.at_level(logging.INFO, logger=logger.name):
        repo = _Repo(deleted)
        with _bound(repo):
            metrics = step.run_delete_empty_journals(None, logger)
    assert metrics.extras["journals_deleted"] == 1
    assert "101021 « Livestock Science » (IntechOpen, sans ISSN)" in caplog.text


def test_without_empty_journal_nothing_is_logged(caplog):
    logger = logging.getLogger("test_revues_vides_aucune")
    with caplog.at_level(logging.INFO, logger=logger.name):
        repo = _Repo([])
        with _bound(repo):
            metrics = step.run_delete_empty_journals(None, logger)
    assert metrics.total == 0
    assert caplog.text == ""
