"""Tests de l'enchaînement de la phase `fetch_stale` selon le mode."""

import logging

from application.pipeline.extract.fetch_stale import run_phase
from application.pipeline.metrics import PhaseMetrics


def _run(mode: str, refreshed: list[str], logger: logging.Logger) -> PhaseMetrics:
    def refresh_one(source: str, years: list[int] | None) -> PhaseMetrics:
        refreshed.append(source)
        return PhaseMetrics()

    return run_phase(
        mode=mode,
        sources={"openalex"},
        include_wos=False,
        year=None,
        start_year=None,
        refresh_one=refresh_one,
        credentials_missing=lambda source: None,
        get_years_for_window=lambda start_year: None,
        logger=logger,
    )


def test_mode_daily_saute_la_phase(caplog):
    logger = logging.getLogger("test_fetch_stale_daily")
    refreshed: list[str] = []
    with caplog.at_level(logging.INFO, logger=logger.name):
        _run("daily", refreshed, logger)
    assert refreshed == []
    assert "Sautée en mode daily" in caplog.text


def test_mode_full_rafraichit_les_sources():
    refreshed: list[str] = []
    _run("full", refreshed, logging.getLogger("test_fetch_stale_full"))
    assert refreshed == ["openalex"]
