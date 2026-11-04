"""Phase `harvest` : sélection des sources par mode, sources non configurées ou indisponibles sautées.

Le moissonnage d'une source (`run_harvest`), la date du dernier moissonnage quotidien et le périmètre d'extraction sont remplacés : la phase se teste sans I/O.
"""

import logging
from collections.abc import Callable
from datetime import date

import pytest

from pipeline.ingestion.common import harvest
from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import (
    signal_source_unavailable,
    signal_source_unconfigured,
)
from pipeline.task_runner import run_phase
from pipeline.transformation.structures import perimeter
from pipeline.transformation.structures.perimeter import EmptyExtractionPerimeterError

_HARVEST = next(phase for phase in PHASES if phase.name == "harvest")

type HarvestOne = Callable[..., PhaseMetrics]


@pytest.fixture
def lancer(monkeypatch, contexte):
    """Renvoie l'exécution de la phase, chaque source moissonnée par `harvest_one(ctx, source, window)`."""

    def _lancer(
        harvest_one: HarvestOne,
        *,
        last_daily: date | None = None,
        structures: list[int] | None = None,
        **options,
    ) -> PhaseMetrics:
        monkeypatch.setattr(
            harvest,
            "run_harvest",
            lambda ctx, source, _harvester, window: harvest_one(ctx, source, window),
        )
        monkeypatch.setattr(harvest, "get_last_daily_harvest_date", lambda: last_daily)
        monkeypatch.setattr(
            perimeter,
            "get_extraction_structure_ids",
            lambda _conn: [1] if structures is None else structures,
        )
        return run_phase(_HARVEST, contexte(**options))

    return _lancer


def _non_configuree(ctx, source: str) -> PhaseMetrics:
    metrics = PhaseMetrics()
    signal_source_unconfigured(metrics, source, "aucune clé", logger=ctx.logger)
    return metrics


def _indisponible(source: str) -> PhaseMetrics:
    """Renvoie les métriques de l'accès à une source indisponible."""
    metrics = PhaseMetrics()
    signal_source_unavailable(metrics, source, logger=logging.getLogger("test"))
    return metrics


def test_parallel_skips_unconfigured_source(lancer):
    def harvest_one(ctx, source, _window):
        return _non_configuree(ctx, source) if source == "openalex" else PhaseMetrics(new=3)

    metrics = lancer(harvest_one, mode="full", sources={"openalex", "theses"})

    assert {r["key"] for r in metrics.details["table"]["rows"]} == {"theses"}
    assert metrics.new == 3  # les métriques de la source configurée sont reprises
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_since_last_extracts_hal_from_last_date(lancer):
    calls: list[tuple[str, str | None]] = []

    def harvest_one(_ctx, source, window):
        calls.append((source, window.since))
        return PhaseMetrics(new=5)

    metrics = lancer(harvest_one, last_daily=date(2026, 1, 1), mode="daily")

    assert calls == [
        ("hal", "2026-01-01")
    ]  # HAL seul, en incrémental depuis le dernier moissonnage
    assert metrics.details["table"]["rows"][0]["key"] == "hal"


def test_since_last_hal_non_configure(lancer):
    metrics = lancer(lambda ctx, source, _window: _non_configuree(ctx, source), mode="daily")

    assert "table" not in metrics.details
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_toutes_les_sources_suivent_la_fenetre_d_annees(lancer):
    seen: dict[str, tuple[int, int] | None] = {}

    def harvest_one(_ctx, source, window):
        seen[source] = window.years
        return PhaseMetrics()

    lancer(harvest_one, mode="full", sources={"hal", "theses"}, years=(2020, 2022))

    assert seen["hal"] == (2020, 2022)
    assert seen["theses"] == (2020, 2022)


def test_parallel_skips_unavailable_source(lancer):
    """Une source indisponible (500 répétés sous circuit-breaker) est sautée : la phase se termine en ambre et les autres sources aboutissent."""

    def harvest_one(_ctx, source, _window):
        return _indisponible("hal") if source == "hal" else PhaseMetrics(new=3)

    metrics = lancer(harvest_one, mode="full", sources={"hal", "theses"})

    assert {r["key"] for r in metrics.details["table"]["rows"]} == {"theses"}  # theses aboutit
    assert metrics.new == 3
    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def test_since_last_marks_hal_unavailable(lancer):
    """En quotidien, une source HAL indisponible termine la phase en ambre."""
    metrics = lancer(lambda _ctx, _source, _window: _indisponible("hal"), mode="daily")

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]
    assert "table" not in metrics.details  # aucune source aboutie


def test_empty_extraction_perimeter_stops_the_phase(lancer):
    """Un périmètre d'extraction sans structure arrête la phase avant tout moissonnage."""
    calls: list[str] = []

    def harvest_one(_ctx, source, _window):
        calls.append(source)
        return PhaseMetrics()

    with pytest.raises(EmptyExtractionPerimeterError, match="perimeter_extraction"):
        lancer(harvest_one, structures=[], mode="full")

    assert calls == []
