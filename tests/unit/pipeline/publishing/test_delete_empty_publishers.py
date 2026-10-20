"""Tests de la suppression des éditeurs vides (`pipeline.transformation.publishing.publishers.delete_empty_publishers`)."""

import logging

from pipeline.transformation.publishing.publishers import delete_empty_publishers as step


def test_each_deleted_publisher_is_logged(caplog, monkeypatch):
    monkeypatch.setattr(
        step, "delete_empty_publishers", lambda conn: [(75880, "Elsevier [1981-....]")]
    )
    logger = logging.getLogger("test_editeurs_vides")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = step.run_delete_empty_publishers(None, logger)
    assert metrics.extras["publishers_deleted"] == 1
    assert "75880 « Elsevier [1981-....] »" in caplog.text


def test_without_empty_publisher_nothing_is_logged(caplog, monkeypatch):
    monkeypatch.setattr(step, "delete_empty_publishers", lambda conn: [])
    logger = logging.getLogger("test_editeurs_vides_aucun")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = step.run_delete_empty_publishers(None, logger)
    assert metrics.total == 0
    assert caplog.text == ""
