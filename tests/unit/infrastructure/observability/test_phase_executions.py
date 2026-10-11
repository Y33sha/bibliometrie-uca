"""Parties pures de la capture d'exécution de phase (sans base)."""

import datetime

from infrastructure.observability.phase_executions import PhaseExecutionRecorder
from pipeline.metrics import PhaseMetrics


def test_recorder_desactive_est_noop():
    """Un recorder sans connexion ne persiste rien et ne lève jamais."""
    recorder = PhaseExecutionRecorder(None, None, mode="full", sources=["hal"])
    assert recorder.run_id is None
    recorder.record(
        phase="normalize",
        started_at=datetime.datetime.now(datetime.UTC),
        status="ok",
        metrics=PhaseMetrics().to_payload(1.0),
        signals=[],
        details={},
    )
    recorder.close()
