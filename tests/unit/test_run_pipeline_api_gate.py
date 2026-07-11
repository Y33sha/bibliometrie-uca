"""Gate de configuration partagé par les phases qui interrogent une API.

`filter_configured` saute les sources dont les credentials manquent (signal
`source_unconfigured`) avant toute requête, et ne retourne que les configurées ;
`phase_oa_status` s'en sert comme garde d'entrée.
"""

import logging
from unittest.mock import AsyncMock, patch

import run_pipeline
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.signals import filter_configured

_RUN_ENRICH = "application.pipeline.oa_status.phase.run"
_LOG = logging.getLogger("test")


def test_filter_configured_filters_and_signals():
    reasons = {
        "scanr": "credentials absents (config.scanr_username / config.scanr_password)",
        "openalex": None,
        "crossref": "email polite pool absent (config.polite_pool_email)",
    }
    metrics = PhaseMetrics()
    kept = filter_configured(
        ["scanr", "openalex", "crossref"],
        metrics,
        credentials_missing=lambda source: reasons[source],
        logger=_LOG,
        phase="cross_imports",
    )

    assert kept == ["openalex"]  # seule la source configurée est retournée
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured", "source_unconfigured"]
    skipped = sorted(s["message"].split(" ", 1)[0] for s in metrics.signals)
    assert skipped == ["crossref", "scanr"]


def test_filter_configured_all_configured_no_signal():
    metrics = PhaseMetrics()
    kept = filter_configured(
        ["hal", "openalex"],
        metrics,
        credentials_missing=lambda source: None,
        logger=_LOG,
        phase="refresh_stale",
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
        patch(_RUN_ENRICH, new_callable=AsyncMock) as run_step,
    ):
        metrics = run_pipeline.phase_oa_status()

    run_step.assert_not_called()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_phase_oa_status_runs_with_email():
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch("infrastructure.sources.config.source_credentials_missing", return_value=None),
        patch("infrastructure.sources.config.get_api_base_urls", return_value={"unpaywall": "u"}),
        patch("infrastructure.sources.config.get_polite_pool_email_optional", return_value="e@x"),
        patch("infrastructure.repositories.publication_repository"),
        patch(_RUN_ENRICH, new_callable=AsyncMock, return_value=PhaseMetrics(new=4)) as run_step,
    ):
        metrics = run_pipeline.phase_oa_status()

    run_step.assert_called_once()
    assert metrics.new == 4
    assert metrics.signals == []
