"""Accès à une source (`access_source`), par lequel passe tout appel à une API tierce.

Sans identifiants, l'étape est sautée avec un signal `source_unconfigured`, avant toute requête. Une source indisponible ou un circuit coupé donnent un signal `source_unavailable`.
"""

import logging
from unittest.mock import AsyncMock, patch

from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications import oa_status

_RUN_ENRICH = "pipeline.transformation.publications.oa_status._verifier"
_LOG = logging.getLogger("test")


def _access(execute, *, missing=None):
    return access_source(
        "crossref", execute, phase="test", logger=_LOG, credentials_missing=lambda _source: missing
    )


def test_sans_identifiants_l_etape_est_sautee():
    appels = []

    metrics = _access(lambda breaker: appels.append(breaker) or PhaseMetrics(), missing="absent")

    assert appels == []
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_avec_identifiants_l_etape_recoit_le_circuit_breaker():
    metrics = _access(lambda breaker: PhaseMetrics(new=breaker.threshold))

    assert metrics.new > 0
    assert metrics.signals == []


def test_source_indisponible_signalee():
    def execute(breaker):
        raise SourceUnavailableError("crossref")

    metrics = _access(execute)

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def test_circuit_coupe_signale():
    def execute(breaker):
        for _ in range(breaker.threshold):
            breaker.record_failure()
        return PhaseMetrics()

    metrics = _access(execute)

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def test_phase_oa_status_skips_without_email():
    with (
        patch("pipeline.runtime.execution.get_sync_engine"),
        patch(_RUN_ENRICH, new_callable=AsyncMock) as run_step,
    ):
        metrics = oa_status.build().run(
            phase_context(RunOptions(), credentials_missing=lambda _source: "adresse absente")
        )

    run_step.assert_not_called()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_phase_oa_status_runs_with_email():
    with (
        patch("pipeline.runtime.execution.get_sync_engine"),
        patch("pipeline.http.polite_pool.get_polite_pool_email_optional", return_value="e@x"),
        patch(_RUN_ENRICH, new_callable=AsyncMock, return_value=PhaseMetrics(new=4)) as run_step,
    ):
        metrics = oa_status.build().run(
            phase_context(RunOptions(), credentials_missing=lambda _source: None)
        )

    run_step.assert_called_once()
    assert metrics.new == 4
    assert metrics.signals == []
