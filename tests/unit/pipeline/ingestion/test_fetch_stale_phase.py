"""Tests de l'enchaînement de la phase `fetch_stale` selon le mode."""

import logging

from pipeline.ingestion.common.fetch_stale import FetchStalePhase
from pipeline.runtime.observability.metrics import PhaseMetrics


def _run(contexte, mode: str, refreshed: list[str]) -> PhaseMetrics:
    def refresh_one(_ctx, source: str, years: list[int] | None) -> PhaseMetrics:
        refreshed.append(source)
        return PhaseMetrics()

    return FetchStalePhase(
        refresh_one=refresh_one,
        get_years_for_window=lambda _ctx, start_year: None,
    ).run(contexte(mode=mode, sources={"openalex"}))


def test_mode_daily_saute_la_phase(contexte, caplog):
    refreshed: list[str] = []
    with caplog.at_level(logging.INFO, logger="test"):
        _run(contexte, "daily", refreshed)
    assert refreshed == []
    assert "Sautée en mode daily" in caplog.text


def test_mode_full_rafraichit_les_sources(contexte):
    refreshed: list[str] = []
    _run(contexte, "full", refreshed)
    assert refreshed == ["openalex"]
