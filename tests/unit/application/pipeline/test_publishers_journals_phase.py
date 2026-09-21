"""Tests de l'enchaînement de la phase `publishers_journals`."""

import logging

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.publishers_journals import phase


def _run(substep_metrics: PhaseMetrics, logger: logging.Logger) -> PhaseMetrics:
    return phase.run(
        resolve_publishers=lambda: substep_metrics,
        enrich_from_openalex=lambda: PhaseMetrics(),
        check_in_sudoc=lambda: PhaseMetrics(),
        merge_duplicates=lambda: PhaseMetrics(),
        delete_empty=lambda: PhaseMetrics(),
        merge_duplicate_monographs=lambda: PhaseMetrics(),
        delete_empty_monographs=lambda: PhaseMetrics(),
        link_monographs_to_collections=lambda: PhaseMetrics(),
        delete_empty_publishers=lambda: PhaseMetrics(),
        type_proceedings=lambda: PhaseMetrics(),
        learn_doi_namespaces=lambda: PhaseMetrics(),
        enrich_from_doaj=lambda: PhaseMetrics(),
        credentials_missing=lambda source: None,
        logger=logger,
    )


def test_phase_without_work_says_so(caplog):
    logger = logging.getLogger("test_phase_vide")
    with caplog.at_level(logging.INFO, logger=logger.name):
        _run(PhaseMetrics(), logger)
    assert "Rien à faire" in caplog.text


def test_phase_with_work_stays_silent(caplog):
    logger = logging.getLogger("test_phase_travail")
    worked = PhaseMetrics()
    worked.add(total=3)
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = _run(worked, logger)
    assert "Rien à faire" not in caplog.text
    assert metrics.total == 3
