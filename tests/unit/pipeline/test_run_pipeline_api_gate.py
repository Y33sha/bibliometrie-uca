"""Accès à une source (`access_source`), par lequel passe tout appel à une API tierce.

Sans identifiants, l'étape est sautée avec un signal `source_unconfigured`, avant toute requête. Une source indisponible ou un circuit coupé donnent un signal `source_unavailable`.
"""

import logging
from unittest.mock import patch

from pipeline.http.circuit_breaker import SourceUnavailableError, get_current_breaker
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications import oa_status

_LOG = logging.getLogger("test")


def _access(execute, *, missing=None):
    return access_source(
        "crossref",
        execute,
        phase="test",
        logger=_LOG,
        credentials_missing=lambda _source: missing,
        request_budget=lambda _source: None,
    )


def test_sans_identifiants_l_etape_est_sautee():
    appels = []

    metrics = _access(lambda: appels.append(True) or PhaseMetrics(), missing="absent")

    assert appels == []
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_avec_identifiants_l_etape_tourne_sous_le_circuit_breaker_de_la_source():
    sources = []

    def execute():
        breaker = get_current_breaker()
        sources.append(breaker and breaker.source)
        return PhaseMetrics()

    metrics = _access(execute)

    assert sources == ["crossref"]
    assert get_current_breaker() is None
    assert metrics.signals == []


def test_le_rythme_suit_le_budget_de_la_source():
    rythmes = []

    def execute():
        breaker = get_current_breaker()
        rythmes.append(breaker and breaker.pace)
        return PhaseMetrics()

    access_source(
        "crossref",
        execute,
        phase="test",
        logger=_LOG,
        credentials_missing=lambda _source: None,
        request_budget=lambda source: 5 if source == "crossref" else None,
    )

    assert rythmes[0] is not None


def test_source_indisponible_signalee():
    def execute():
        raise SourceUnavailableError("crossref")

    metrics = _access(execute)

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def test_circuit_coupe_signale():
    def execute():
        breaker = get_current_breaker()
        assert breaker is not None
        for _ in range(breaker.threshold):
            breaker.record_failure()
        return PhaseMetrics()

    metrics = _access(execute)

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def _run_oa_status(credentials_missing) -> tuple[PhaseMetrics, list[oa_status.DoiService]]:
    """Exécute la phase `oa_status` sans réseau ni base, et renvoie ses métriques et les services interrogés."""
    services = []

    def run(task, _ctx):
        services.append(task.service)
        return PhaseMetrics(new=4)

    with (
        patch("pipeline.runtime.execution.get_sync_engine"),
        patch.object(oa_status.DoiLookupTask, "run", autospec=True, side_effect=run),
    ):
        metrics = oa_status.build().run(
            phase_context(
                RunOptions(),
                credentials_missing=credentials_missing,
                request_budget=lambda _source: None,
            )
        )
    return metrics, services


def test_phase_oa_status_skips_unpaywall_without_email():
    metrics, services = _run_oa_status(
        lambda source: "adresse absente" if source == "unpaywall" else None
    )

    assert services == [oa_status.DOI_ORG]
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_phase_oa_status_runs_with_email():
    metrics, services = _run_oa_status(lambda _source: None)

    assert services == [oa_status.DOI_ORG, oa_status.UNPAYWALL]
    assert metrics.new == 4
    assert metrics.signals == []
