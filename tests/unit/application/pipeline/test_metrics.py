"""Sérialisation des métriques de phase vers le payload de transport."""

from application.pipeline.metrics import PhaseMetrics


def test_to_payload():
    metrics = PhaseMetrics(new=3, updated=1, total=4)
    metrics.extras["tagged"] = 2
    assert metrics.to_payload(duration_s=12.5) == {
        "new": 3,
        "updated": 1,
        "unchanged": 0,
        "total": 4,
        "errors": 0,
        "extras": {"tagged": 2},
        "duration_s": 12.5,
    }
