"""Accès à une source (`access_source`), par lequel passe tout appel à une API tierce.

Sans identifiants, l'étape est sautée avec un signal `source_unconfigured`, avant toute requête. Une source indisponible ou un circuit coupé donnent un signal `source_unavailable`.
"""

import dataclasses
import logging
from unittest.mock import patch

from pipeline.http.circuit_breaker import SourceUnavailableError, get_current_breaker
from pipeline.phases import PHASES
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from pipeline.transformation.dois import lookups

_LOG = logging.getLogger("test")


def _access(execute, *, missing=None):
    return access_source(
        "crossref",
        execute,
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


def _run_lookups(credentials_missing) -> tuple[PhaseMetrics, list[lookups.DoiService]]:
    """Exécute les interrogations de doi.org et d'Unpaywall de la phase `dois`, sans réseau ni base, et renvoie leurs métriques et les services interrogés."""
    services = []

    def run(task, _ctx):
        services.append(task.service)
        return PhaseMetrics(new=4)

    phase = next(p for p in PHASES if p.name == "dois")
    with patch.object(lookups.DoiLookupTask, "run", autospec=True, side_effect=run):
        metrics = run_phase(
            dataclasses.replace(phase, children=lookups.TASKS),
            phase_context(
                RunOptions(),
                credentials_missing=credentials_missing,
                request_budget=lambda _source: None,
            ),
        )
    return metrics, services


def test_unpaywall_sautee_sans_adresse():
    metrics, services = _run_lookups(
        lambda source: "adresse absente" if source == "unpaywall" else None
    )

    assert services == [lookups.DOI_ORG]
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_unpaywall_interrogee_avec_adresse():
    metrics, services = _run_lookups(lambda _source: None)

    assert services == [lookups.DOI_ORG, lookups.UNPAYWALL]
    assert metrics.new == 8  # somme des deux services
    assert metrics.signals == []
