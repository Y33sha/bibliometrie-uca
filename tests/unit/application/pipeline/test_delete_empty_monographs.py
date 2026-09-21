"""Tests de la suppression des monographies vides (`application.pipeline.publishers_journals.delete_empty_monographs`)."""

import logging

from application.pipeline.publishers_journals.delete_empty_monographs import (
    run_delete_empty_monographs,
)


class _Repo:
    def __init__(self, deleted: list[tuple[int, str]]) -> None:
        self._deleted = deleted

    def delete_empty_monographs(self) -> list[tuple[int, str]]:
        return self._deleted


def test_each_deleted_monograph_is_logged(caplog):
    logger = logging.getLogger("test_monographies_vides")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_delete_empty_monographs(
            logger, monograph_repo=_Repo([(12, "Le Paris du Moyen Âge")])
        )
    assert metrics.extras["monographs_deleted"] == 1
    assert "12 « Le Paris du Moyen Âge »" in caplog.text


def test_without_empty_monograph_nothing_is_logged(caplog):
    logger = logging.getLogger("test_monographies_vides_aucune")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_delete_empty_monographs(logger, monograph_repo=_Repo([]))
    assert metrics.total == 0
    assert caplog.text == ""
