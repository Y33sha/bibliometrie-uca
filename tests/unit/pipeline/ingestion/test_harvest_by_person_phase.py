"""Tests de l'enchaînement de la phase `harvest_by_person` selon le mode."""

import logging

import pytest

from pipeline.ingestion.common import harvest_by_person
from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase

_PHASE = next(phase for phase in PHASES if phase.name == "harvest_by_person")


@pytest.fixture
def interrogees(monkeypatch) -> list[str]:
    """Sources interrogées par la phase, sans réseau."""
    sources: list[str] = []

    def run_harvest(_ctx, source, _harvester, _window) -> PhaseMetrics:
        sources.append(source)
        return PhaseMetrics()

    monkeypatch.setattr(harvest_by_person, "run_harvest", run_harvest)
    return sources


def test_mode_daily_saute_la_phase(contexte, caplog, interrogees):
    with caplog.at_level(logging.INFO, logger="test"):
        run_phase(_PHASE, contexte(mode="daily", sources={"openalex"}))
    assert interrogees == []
    assert "Sautée en mode daily" in caplog.text


def test_mode_full_moissonne_les_sources_demandees(contexte, interrogees):
    run_phase(_PHASE, contexte(mode="full", sources={"openalex"}))
    assert interrogees == ["openalex"]
