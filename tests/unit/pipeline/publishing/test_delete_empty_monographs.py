"""Tests de la suppression des monographies vides (`pipeline.transformation.publishing.monographs.delete_empty_monographs`)."""

import logging

from pipeline.transformation.publishing.monographs import delete_empty_monographs as step


def _run(monkeypatch, logger, deleted: list[tuple[int, str]]):
    monkeypatch.setattr(step, "delete_empty_monographs", lambda conn: deleted)
    return step.run_delete_empty_monographs(None, logger)


def test_each_deleted_monograph_is_logged(caplog, monkeypatch):
    logger = logging.getLogger("test_monographies_vides")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = _run(monkeypatch, logger, [(12, "Le Paris du Moyen Âge")])
    assert metrics.extras["monographs_deleted"] == 1
    assert "12 « Le Paris du Moyen Âge »" in caplog.text


def test_without_empty_monograph_nothing_is_logged(caplog, monkeypatch):
    logger = logging.getLogger("test_monographies_vides_aucune")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = _run(monkeypatch, logger, [])
    assert metrics.total == 0
    assert caplog.text == ""
