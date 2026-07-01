"""Gate de configuration partagé par les phases qui interrogent une API par
identifiant (cross-import, refresh stale).

`_configured_api_targets` saute les sources dont les credentials manquent (signal
`source_unconfigured`) avant toute requête, et ne retourne que les configurées.
"""

from unittest.mock import patch

import run_pipeline
from application.pipeline.metrics import PhaseMetrics


def test_configured_api_targets_filters_and_signals():
    reasons = {
        "scanr": "credentials absents (config.scanr_username / config.scanr_password)",
        "openalex": None,
        "crossref": "email polite pool absent (config.polite_pool_email)",
    }
    metrics = PhaseMetrics()
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch(
            "infrastructure.sources.config.source_credentials_missing",
            side_effect=lambda conn, source: reasons[source],
        ),
    ):
        kept = run_pipeline._configured_api_targets(
            ["scanr", "openalex", "crossref"], metrics, phase="cross_imports"
        )

    assert kept == ["openalex"]  # seule la source configurée est retournée
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured", "source_unconfigured"]
    skipped = sorted(s["message"].split(" ", 1)[0] for s in metrics.signals)
    assert skipped == ["crossref", "scanr"]


def test_configured_api_targets_all_configured_no_signal():
    metrics = PhaseMetrics()
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch(
            "infrastructure.sources.config.source_credentials_missing",
            side_effect=lambda conn, source: None,
        ),
    ):
        kept = run_pipeline._configured_api_targets(
            ["hal", "openalex"], metrics, phase="refresh_stale"
        )

    assert kept == ["hal", "openalex"]
    assert metrics.signals == []


def test_phase_oa_status_skips_without_email():
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch(
            "infrastructure.sources.config.source_credentials_missing",
            return_value="email polite pool absent (config.polite_pool_email)",
        ),
        patch.object(run_pipeline, "_run_enrich_oa_status") as run_step,
    ):
        metrics = run_pipeline.phase_oa_status()

    run_step.assert_not_called()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_phase_oa_status_runs_with_email():
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch("infrastructure.sources.config.source_credentials_missing", return_value=None),
        patch.object(
            run_pipeline, "_run_enrich_oa_status", return_value=PhaseMetrics(new=4)
        ) as run_step,
    ):
        metrics = run_pipeline.phase_oa_status()

    run_step.assert_called_once()
    assert metrics.new == 4
    assert metrics.signals == []
