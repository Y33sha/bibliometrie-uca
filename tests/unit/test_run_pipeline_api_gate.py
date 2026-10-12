"""Gate de configuration partagé par les phases qui interrogent une API.

`filter_configured` saute les sources dont les credentials manquent (signal
`source_unconfigured`) avant toute requête, et ne retourne que les configurées ;
la phase `oa_status` s'en sert comme garde d'entrée.
"""

import logging
from unittest.mock import AsyncMock, patch

from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import filter_configured
from pipeline.transformation.publications import oa_status

_RUN_ENRICH = "pipeline.transformation.publications.oa_status._verifier"
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
        phase="fetch_missing",
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
        phase="fetch_stale",
    )

    assert kept == ["hal", "openalex"]
    assert metrics.signals == []


def test_phase_oa_status_skips_without_email():
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch(
            "pipeline.runtime.config.source_credentials_missing",
            return_value="email polite pool absent (config.polite_pool_email)",
        ),
        patch(_RUN_ENRICH, new_callable=AsyncMock) as run_step,
    ):
        metrics = oa_status.build().run(phase_context(RunOptions()))

    run_step.assert_not_called()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_phase_oa_status_runs_with_email():
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch("pipeline.runtime.config.source_credentials_missing", return_value=None),
        patch("pipeline.runtime.config.get_polite_pool_email_optional", return_value="e@x"),
        patch(_RUN_ENRICH, new_callable=AsyncMock, return_value=PhaseMetrics(new=4)) as run_step,
    ):
        metrics = oa_status.build().run(phase_context(RunOptions()))

    run_step.assert_called_once()
    assert metrics.new == 4
    assert metrics.signals == []
