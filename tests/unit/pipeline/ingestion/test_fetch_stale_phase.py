"""Tests de l'enchaînement de la phase `fetch_stale` selon le mode."""

import pytest

from pipeline.ingestion.common import fetch_stale
from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase

_PHASE = next(phase for phase in PHASES if phase.name == "fetch_stale")


@pytest.fixture
def relues(monkeypatch) -> list[str]:
    """Sources relues par la phase, sans réseau ni base."""
    sources: list[str] = []

    def run_one(_ctx, source: str, _years) -> PhaseMetrics:
        sources.append(source)
        return PhaseMetrics()

    monkeypatch.setattr(fetch_stale, "_run_fetch_stale", run_one)
    monkeypatch.setattr(fetch_stale, "window_years", lambda _conn, *, start_year, year: None)
    return sources


def test_mode_daily_saute_la_phase(contexte, relues):
    run_phase(_PHASE, contexte(mode="daily", sources={"openalex"}))
    assert relues == []


def test_mode_full_rafraichit_les_sources_demandees(contexte, relues):
    run_phase(_PHASE, contexte(mode="full", sources={"openalex"}))
    assert relues == ["openalex"]
