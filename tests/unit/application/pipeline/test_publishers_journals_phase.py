"""Tests de l'enchaînement de la phase `publishers_journals`."""

import logging

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.publishers_journals.phase import PublishersJournalsPhase


def _run(contexte, substep_metrics: PhaseMetrics) -> PhaseMetrics:
    return PublishersJournalsPhase(
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
        type_proceedings_volumes=lambda: PhaseMetrics(),
        learn_doi_namespaces=lambda: PhaseMetrics(),
        enrich_from_doaj=lambda: PhaseMetrics(),
        credentials_missing=lambda source: None,
    ).run(contexte())


def test_phase_without_work_says_so(contexte, caplog):
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, PhaseMetrics())
    assert "Rien à faire" in caplog.text


def test_phase_with_work_stays_silent(contexte, caplog):
    worked = PhaseMetrics()
    worked.add(total=3)
    with caplog.at_level(logging.INFO, logger="test"):
        metrics = _run(contexte, worked)
    assert "Rien à faire" not in caplog.text
    assert metrics.total == 3
