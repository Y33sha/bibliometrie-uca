"""Parties pures de la capture d'exécution de phase (sans base)."""

import datetime

from application.pipeline.metrics import PhaseMetrics
from infrastructure.observability.phase_executions import PhaseExecutionRecorder


def test_recorder_desactive_est_noop():
    """Un recorder sans connexion ne relève rien et ne lève jamais."""
    recorder = PhaseExecutionRecorder(None, None, mode="full", sources=["hal"])
    assert recorder.run_id is None
    assert recorder.before_volumes(("source_publications",)) is None
    recorder.record(
        phase="normalize",
        started_at=datetime.datetime.now(datetime.UTC),
        status="ok",
        metrics=PhaseMetrics().to_payload(1.0),
        signals=[],
        details={},
        before_volumes=None,
    )
    recorder.close()
