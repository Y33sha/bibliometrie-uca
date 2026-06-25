"""Parties pures de la capture d'exécution de phase (sans base)."""

import datetime

from application.pipeline.metrics import PhaseMetrics
from infrastructure.observability.phase_executions import (
    PhaseExecutionRecorder,
    metrics_to_payload,
)


def test_metrics_to_payload():
    metrics = PhaseMetrics(new=3, updated=1, total=4)
    metrics.extras["tagged"] = 2
    payload = metrics_to_payload(metrics, duration_s=12.5)
    assert payload == {
        "new": 3,
        "updated": 1,
        "unchanged": 0,
        "total": 4,
        "errors": 0,
        "extras": {"tagged": 2},
        "duration_s": 12.5,
    }


def test_recorder_desactive_est_noop():
    """Un recorder sans connexion ne relève rien et ne lève jamais."""
    recorder = PhaseExecutionRecorder(None, None, mode="full", sources=["hal"])
    assert recorder.run_id is None
    assert recorder.input_volumes("normalize") is None
    recorder.record(
        phase="normalize",
        started_at=datetime.datetime.now(datetime.UTC),
        status="ok",
        metrics=metrics_to_payload(PhaseMetrics(), 1.0),
        signals=[],
        input_volumes=None,
    )
    recorder.close()
