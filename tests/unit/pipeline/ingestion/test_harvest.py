"""Orchestrateur de la phase `harvest` : sélection des sources par mode, sources non configurées sautées.

Les dépendances techniques (moissonnage d'une source, parallélisme, dernière date) sont injectées. L'orchestrateur se teste donc sans I/O ni threads : `run_parallel` est simulé par une exécution synchrone déterministe.
"""

import logging
from datetime import date

import pytest

from pipeline.ingestion.common.harvest import HarvestOne, HarvestPhase
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import (
    signal_source_unavailable,
    signal_source_unconfigured,
)
from pipeline.transformation.structures.perimeter import EmptyExtractionPerimeterError


def _sync_run_parallel(thunks):
    """Exécute les thunks en séquence, avec le contrat de `run_parallel`."""
    return {label: thunk() for label, thunk in thunks.items()}


def _phase(
    harvest_one: HarvestOne, *, last_daily: date | None = None, structures: int = 1
) -> HarvestPhase:
    return HarvestPhase(
        count_extraction_structures=lambda _ctx: structures,
        harvest_one=harvest_one,
        run_parallel=_sync_run_parallel,
        get_last_daily_harvest_date=lambda: last_daily,
    )


def test_parallel_skips_unconfigured_source(contexte):
    def harvest_one(ctx, source, _args):
        if source == "openalex":
            metrics = PhaseMetrics()
            signal_source_unconfigured(
                metrics, source, "aucune clé", logger=ctx.logger, phase="harvest"
            )
            return metrics
        return PhaseMetrics(new=3)

    metrics = _phase(harvest_one).run(contexte(mode="full", sources={"openalex", "theses"}))

    assert {r["key"] for r in metrics.details["table"]["rows"]} == {"theses"}
    assert metrics.new == 3  # les métriques de la source configurée sont reprises
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_since_last_extracts_hal_from_last_date(contexte):
    calls: list[tuple[str, str | None]] = []

    def harvest_one(_ctx, source, args):
        calls.append((source, args.since))
        return PhaseMetrics(new=5)

    metrics = _phase(harvest_one, last_daily=date(2026, 1, 1)).run(contexte(mode="daily"))

    assert calls == [
        ("hal", "2026-01-01")
    ]  # HAL seul, en incrémental depuis le dernier moissonnage
    assert metrics.details["table"]["rows"][0]["key"] == "hal"


def test_toutes_les_sources_suivent_la_fenetre_d_annees(contexte):
    seen: dict[str, tuple[int | None, int | None]] = {}

    def harvest_one(_ctx, source, args):
        seen[source] = (args.start_year, args.year)
        return PhaseMetrics()

    _phase(harvest_one).run(contexte(mode="full", sources={"hal", "theses"}, start_year=2020))

    assert seen["hal"] == (2020, None)
    assert seen["theses"] == (2020, None)


def _indisponible(source: str) -> PhaseMetrics:
    """Renvoie les métriques de l'accès à une source indisponible."""
    metrics = PhaseMetrics()
    signal_source_unavailable(metrics, source, logger=logging.getLogger("test"), phase="harvest")
    return metrics


def test_parallel_skips_unavailable_source(contexte):
    """Une source indisponible (500 répétés sous circuit-breaker) est sautée : la phase se termine en ambre et les autres sources aboutissent."""

    def harvest_one(_ctx, source, _args):
        if source == "hal":
            return _indisponible("hal")
        return PhaseMetrics(new=3)

    metrics = _phase(harvest_one).run(contexte(mode="full", sources={"hal", "theses"}))

    assert {r["key"] for r in metrics.details["table"]["rows"]} == {"theses"}  # theses aboutit
    assert metrics.new == 3
    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def test_since_last_marks_hal_unavailable(contexte):
    """En quotidien, une source HAL indisponible termine la phase en ambre."""

    def harvest_one(_ctx, _source, _args):
        return _indisponible("hal")

    metrics = _phase(harvest_one).run(contexte(mode="daily"))

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]
    assert "table" not in metrics.details  # aucune source aboutie


def test_empty_extraction_perimeter_stops_the_phase(contexte):
    """Un périmètre d'extraction sans structure arrête la phase avant tout moissonnage."""
    calls: list[str] = []

    def harvest_one(_ctx, source, _args):
        calls.append(source)
        return PhaseMetrics()

    with pytest.raises(EmptyExtractionPerimeterError, match="perimeter_extraction"):
        _phase(harvest_one, structures=0).run(contexte(mode="full"))

    assert calls == []
