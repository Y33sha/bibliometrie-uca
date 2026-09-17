"""Tests de la suppression des éditeurs vides (`application.pipeline.publishers_journals.delete_empty_publishers`)."""

import logging

from application.pipeline.publishers_journals.delete_empty_publishers import (
    run_delete_empty_publishers,
)


class _Repo:
    def __init__(self, deleted: list[tuple[int, str]]) -> None:
        self._deleted = deleted

    def delete_empty_publishers(self) -> list[tuple[int, str]]:
        return self._deleted


def test_each_deleted_publisher_is_logged(caplog):
    logger = logging.getLogger("test_editeurs_vides")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_delete_empty_publishers(
            logger, publisher_repo=_Repo([(75880, "Elsevier [1981-....]")])
        )
    assert metrics.extras["publishers_deleted"] == 1
    assert "75880 « Elsevier [1981-....] »" in caplog.text


def test_without_empty_publisher_nothing_is_logged(caplog):
    logger = logging.getLogger("test_editeurs_vides_aucun")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_delete_empty_publishers(logger, publisher_repo=_Repo([]))
    assert metrics.total == 0
    assert caplog.text == ""
