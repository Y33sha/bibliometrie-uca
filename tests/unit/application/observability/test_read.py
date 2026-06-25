"""Calculs de lecture : rendement et écart de durée (sans base)."""

import datetime

from application.observability.read import compute_yield, duration_ratio, median_duration
from application.ports.pipeline.phase_executions import PhaseExecution


def _execution(phase: str, *, input_volumes=None, output_volumes=None) -> PhaseExecution:
    return PhaseExecution(
        run_id=1,
        phase=phase,
        started_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
        ended_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
        mode="full",
        sources=["hal"],
        status="ok",
        metrics={
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "total": 0,
            "errors": 0,
            "extras": {},
            "duration_s": 1.0,
        },
        input=input_volumes,
        output=output_volumes,
    )


def test_yield_dedup_publications():
    execution = _execution(
        "publications",
        input_volumes={"source_publications": 1000},
        output_volumes={"publications": 800},
    )
    assert compute_yield(execution) == 0.8


def test_yield_none_pour_extract_sans_entree_locale():
    execution = _execution("extract", output_volumes={"staging": 500})
    assert compute_yield(execution) is None


def test_yield_none_si_observables_manquants():
    assert compute_yield(_execution("publications")) is None


def test_yield_none_si_entree_nulle():
    execution = _execution(
        "publications",
        input_volumes={"source_publications": 0},
        output_volumes={"publications": 0},
    )
    assert compute_yield(execution) is None


def test_yield_none_phase_hors_graphe():
    execution = _execution(
        "phase_retiree",
        input_volumes={"x": 10},
        output_volumes={"y": 5},
    )
    assert compute_yield(execution) is None


def test_median_duration():
    assert median_duration([3.0, 1.0, 2.0]) == 2.0
    assert median_duration([]) is None


def test_duration_ratio():
    assert duration_ratio(10.0, 5.0) == 2.0
    assert duration_ratio(10.0, None) is None
    assert duration_ratio(10.0, 0.0) is None
