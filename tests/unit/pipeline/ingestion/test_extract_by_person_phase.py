"""Tests de l'enchaînement de la phase `extract_by_person` selon le mode."""

import logging
from unittest.mock import patch

from pipeline.ingestion.common.extract_by_person import ExtractByPersonPhase
from pipeline.runtime.observability.metrics import PhaseMetrics


def _run(contexte, mode: str, searched: list[str]) -> PhaseMetrics:
    def search_one(source: str, args, breaker) -> PhaseMetrics:
        searched.append(source)
        return PhaseMetrics()

    def run_sequential(thunks):
        return {label: thunk() for label, thunk in thunks.items()}

    with patch("pipeline.runtime.config.source_credentials_missing", return_value=None):
        return ExtractByPersonPhase(search_one=search_one, run_parallel=run_sequential).run(
            contexte(mode=mode, sources={"openalex"})
        )


def test_mode_daily_saute_la_phase(contexte, caplog):
    searched: list[str] = []
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, "daily", searched)
    assert searched == []
    assert "Moissonnage par personne" in caplog.text
    assert "Sautée en mode daily" in caplog.text


def test_mode_full_moissonne_les_sources(contexte):
    searched: list[str] = []
    _run(contexte, "full", searched)
    assert searched == ["openalex"]
